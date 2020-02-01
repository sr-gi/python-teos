from getopt import getopt
from sys import argv, exit
from signal import signal, SIGINT, SIGQUIT, SIGTERM

from common.logger import Logger
from common.cryptographer import Cryptographer

from pisa import config, LOG_PREFIX
from pisa.api import API
from pisa.watcher import Watcher
from pisa.builder import Builder
from pisa.responder import Responder
from pisa.db_manager import DBManager
from pisa.chain_monitor import ChainMonitor
from pisa.block_processor import BlockProcessor
from pisa.tools import can_connect_to_bitcoind, in_correct_network

logger = Logger(actor="Daemon", log_name_prefix=LOG_PREFIX)


def handle_signals(signal_received, frame):
    logger.info("Closing connection with appointments db")
    db_manager.db.close()
    chain_monitor.terminate = True

    logger.info("Shutting down PISA")
    exit(0)


def main():
    global db_manager, chain_monitor

    signal(SIGINT, handle_signals)
    signal(SIGTERM, handle_signals)
    signal(SIGQUIT, handle_signals)

    logger.info("Starting PISA")
    db_manager = DBManager(config.get("DB_PATH"))

    if not can_connect_to_bitcoind():
        logger.error("Can't connect to bitcoind. Shutting down")

    elif not in_correct_network(config.get("BTC_NETWORK")):
        logger.error("bitcoind is running on a different network, check conf.py and bitcoin.conf. Shutting down")

    else:
        try:
            secret_key_der = Cryptographer.load_key_file(config.get("PISA_SECRET_KEY"))
            if not secret_key_der:
                raise IOError("PISA private key can't be loaded")

            watcher = Watcher(db_manager, Responder(db_manager), secret_key_der, config)

            # Create the chain monitor and start monitoring the chain
            chain_monitor = ChainMonitor(watcher.block_queue, watcher.responder.block_queue)

            watcher_appointments_data = db_manager.load_watcher_appointments()
            responder_trackers_data = db_manager.load_responder_trackers()

            if len(watcher_appointments_data) == 0 and len(responder_trackers_data) == 0:
                logger.info("Fresh bootstrap")

                watcher.awake()
                watcher.responder.awake()

            else:
                logger.info("Bootstrapping from backed up data")

                # Update the Watcher backed up data if found.
                if len(watcher_appointments_data) != 0:
                    watcher.appointments, watcher.locator_uuid_map = Builder.build_appointments(
                        watcher_appointments_data
                    )

                # Update the Responder with backed up data if found.
                if len(responder_trackers_data) != 0:
                    watcher.responder.trackers, watcher.responder.tx_tracker_map = Builder.build_trackers(
                        responder_trackers_data
                    )

                # Awaking components so the states can be updated.
                watcher.awake()
                watcher.responder.awake()

                last_block_watcher = db_manager.load_last_block_hash_watcher()
                last_block_responder = db_manager.load_last_block_hash_responder()

                # Populate the block queues with data if they've missed some while offline. If the blocks of both match
                # we don't perform the search twice.
                block_processor = BlockProcessor()

                # FIXME: 32-reorgs-offline dropped txs are not used at this point.
                last_common_ancestor_watcher, dropped_txs_watcher = block_processor.find_last_common_ancestor(
                    last_block_watcher
                )
                missed_blocks_watcher = block_processor.get_missed_blocks(last_common_ancestor_watcher)

                if last_block_watcher == last_block_responder:
                    dropped_txs_responder = dropped_txs_watcher
                    missed_blocks_responder = missed_blocks_watcher

                else:
                    last_common_ancestor_responder, dropped_txs_responder = block_processor.find_last_common_ancestor(
                        last_block_responder
                    )
                    missed_blocks_responder = block_processor.get_missed_blocks(last_common_ancestor_responder)

                # If only one of the instances needs to be updated, it can be done separately.
                if len(missed_blocks_watcher) == 0 and len(missed_blocks_responder) != 0:
                    Builder.populate_block_queue(watcher.responder.block_queue, missed_blocks_responder)
                    watcher.responder.block_queue.join()

                elif len(missed_blocks_responder) == 0 and len(missed_blocks_watcher) != 0:
                    Builder.populate_block_queue(watcher.block_queue, missed_blocks_watcher)
                    watcher.block_queue.join()

                # Otherwise they need to be updated at the same time, block by block
                elif len(missed_blocks_responder) != 0 and len(missed_blocks_watcher) != 0:
                    Builder.update_states(watcher, missed_blocks_watcher, missed_blocks_responder)

            # Fire the API and the ChainMonitor
            # FIXME: 92-block-data-during-bootstrap-db
            chain_monitor.monitor_chain()
            API(watcher, config=config).start()
        except Exception as e:
            logger.error("An error occurred: {}. Shutting down".format(e))
            exit(1)


if __name__ == "__main__":
    opts, _ = getopt(argv[1:], "", [""])
    for opt, arg in opts:
        # FIXME: Leaving this here for future option/arguments
        pass

    main()
