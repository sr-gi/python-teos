from queue import Queue

from pisa.responder import TransactionTracker
from common.appointment import Appointment


class Builder:
    """
    The :class:`Builder` class is in charge or reconstructing data loaded from the database and build the data
    structures of the :obj:`Watcher <pisa.watcher.Watcher>` and the :obj:`Responder <pisa.responder.Responder>`.
    """

    @staticmethod
    def build_appointments(appointments_data):
        """
        Builds an appointments dictionary (``uuid: Appointment``) and a locator_uuid_map (``locator: uuid``) given a
        dictionary of appointments from the database.

        Args:
            appointments_data (:obj:`dict`): a dictionary of dictionaries representing all the
                :obj:`Watcher <pisa.watcher.Watcher>` appointments stored in the database. The structure is as follows:

                    ``{uuid: {locator: str, start_time: int, ...}, uuid: {locator:...}}``

        Returns:
            :obj:`tuple`: A tuple with two dictionaries. ``appointments`` containing the appointment information in
            :obj:`Appointment <pisa.appointment.Appointment>` objects and ``locator_uuid_map`` containing a map of
            appointment (``uuid:locator``).
        """

        appointments = {}
        locator_uuid_map = {}

        for uuid, data in appointments_data.items():
            appointments[uuid] = {"locator": data.get("locator"), "end_time": data.get("end_time")}

            if data.get("locator") in locator_uuid_map:
                locator_uuid_map[data.get("locator")].append(uuid)

            else:
                locator_uuid_map[data.get("locator")] = [uuid]

        return appointments, locator_uuid_map

    @staticmethod
    def build_trackers(tracker_data):
        """
        Builds a tracker dictionary (``uuid: TransactionTracker``) and a tx_tracker_map (``penalty_txid: uuid``) given
        a dictionary of trackers from the database.

        Args:
            tracker_data (:obj:`dict`): a dictionary of dictionaries representing all the
                :mod:`Responder <pisa.responder.Responder>` trackers stored in the database.
                The structure is as follows:

                    ``{uuid: {locator: str, dispute_txid: str, ...}, uuid: {locator:...}}``

        Returns:
            :obj:`tuple`: A tuple with two dictionaries. ``trackers`` containing the trackers' information in
            :obj:`TransactionTracker <pisa.responder.TransactionTracker>` objects and a ``tx_tracker_map`` containing
            the map of trackers (``penalty_txid: uuid``).

        """

        trackers = {}
        tx_tracker_map = {}

        for uuid, data in tracker_data.items():
            trackers[uuid] = {
                "penalty_txid": data.get("penalty_txid"),
                "locator": data.get("locator"),
                "appointment_end": data.get("appointment_end"),
            }

            if data.get("penalty_txid") in tx_tracker_map:
                tx_tracker_map[data.get("penalty_txid")].append(uuid)

            else:
                tx_tracker_map[data.get("penalty_txid")] = [uuid]

        return trackers, tx_tracker_map

    @staticmethod
    def populate_block_queue(block_queue, missed_blocks):
        """
        Populates a ``Queue`` of block hashes to initialize the :mod:`Watcher <pisa.watcher.Watcher>` or the
        :mod:`Responder <pisa.responder.Responder>` using backed up data.

        Args:
            block_queue (:obj:`Queue`): a ``Queue``
            missed_blocks (:obj:`list`): list of block hashes missed by the Watchtower (do to a crash or shutdown).

        Returns:
            :obj:`Queue`: A ``Queue`` containing all the missed blocks hashes.
        """

        for block in missed_blocks:
            block_queue.put(block)
