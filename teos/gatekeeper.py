from math import ceil
from threading import Lock

from common.tools import is_compressed_pk, is_u4int
from common.cryptographer import Cryptographer
from common.receipts import create_registration_receipt
from common.constants import ENCRYPTED_BLOB_MAX_SIZE_HEX
from common.exceptions import InvalidParameter, InvalidKey, SignatureError


class NotEnoughSlots(ValueError):
    """Raised when trying to subtract more slots than a user has available."""

    pass


class SubscriptionExpired(ValueError):
    """Raised when trying to subtract more slots than a user has available."""

    pass


class AuthenticationFailure(Exception):
    """
    Raised when a user can not be authenticated. Either the user public key cannot be recovered or the user is
    not found within the registered ones.
    """

    pass


class UserInfo:
    """
    Class used to stored information about a user.

    Args:
        available_slots (:obj:`int`): the number of appointment slots available to the user.
        subscription_expiry (:obj:`int`): the block height when the user subscription will expire.
        appointments (:obj:`dict`): a dictionary containing the current appointments of the user. Optional.
    """

    def __init__(self, available_slots, subscription_expiry, appointments=None):
        self.available_slots = available_slots
        self.subscription_expiry = subscription_expiry

        if not appointments:
            # A dictionary of the form uuid:required_slots for each user appointment
            self.appointments = {}
        else:
            self.appointments = appointments

    @classmethod
    def from_dict(cls, user_data):
        """
        Creates a :obj:`UserInfo` instance from a dictionary.

        Args:
            user_data (:obj:`dict`): a dictionary containing all the necessary ``key:value`` pairs.

        Raises:
            :obj:`ValueError`: if any of the dictionary entries is missing.
        """
        available_slots = user_data.get("available_slots")
        appointments = user_data.get("appointments")
        subscription_expiry = user_data.get("subscription_expiry")

        if any(v is None for v in [available_slots, appointments, subscription_expiry]):
            raise ValueError("Wrong appointment data, some fields are missing")

        return cls(available_slots, subscription_expiry, appointments)

    def to_dict(self):
        """Converts a :obj:`UserInfo` instance in a dictionary."""
        return self.__dict__


class Gatekeeper:
    """
    The :class:`Gatekeeper` is in charge of managing the access to the tower. Only registered users are allowed to
    perform actions.

    Attributes:
        subscription_slots (:obj:`int`): The number of slots assigned to a user subscription.
        subscription_duration (:obj:`int`): The expiry assigned to a user subscription.
        expiry_delta (:obj:`int`): The grace period given to the user to renew their subscription.
        block_processor (:obj:`BlockProcessor <teos.block_processor.BlockProcessor>`): A block processor instance to
            get block from bitcoind.
        user_db (:obj:`UsersDBM <teos.user_dbm.UsersDBM>`): A user database manager instance to interact with the
            database.
        registered_users (:obj:`dict`): A map of ``user_pk:user_info``.
        lock (:obj:`Lock`): A lock object to lock access to the Gatekeeper on updates.

    """

    def __init__(self, user_db, block_processor, subscription_slots, subscription_duration, expiry_delta):
        self.subscription_slots = subscription_slots
        self.subscription_duration = subscription_duration
        self.expiry_delta = expiry_delta
        self.block_processor = block_processor
        self.user_db = user_db
        self.registered_users = {
            user_id: UserInfo.from_dict(user_data) for user_id, user_data in user_db.load_all_users().items()
        }
        self.lock = Lock()

    def add_update_user(self, user_id):
        """
        Adds a new user or updates the subscription of an existing one, by adding additional slots.

        Args:
            user_id(:obj:`str`): the public key that identifies the user (33-bytes hex str).

        Returns:
            :obj:`tuple`: A tuple with the number of available slots in the user subscription, the subscription
            expiry (in absolute block height), and the registration_receipt.

        Raises:
            :obj:`InvalidParameter`: if the user_pk does not match the expected format.
        """

        if not is_compressed_pk(user_id):
            raise InvalidParameter("Provided public key does not match expected format (33-byte hex string)")

        if user_id not in self.registered_users:
            self.registered_users[user_id] = UserInfo(
                self.subscription_slots, self.block_processor.get_block_count() + self.subscription_duration
            )
        else:
            # FIXME: For now new calls to register add subscription_slots to the current count and reset the expiry time
            if not is_u4int(self.registered_users[user_id].available_slots + self.subscription_slots):
                raise InvalidParameter("Maximum slots reached for the subscription")

            self.registered_users[user_id].available_slots += self.subscription_slots
            self.registered_users[user_id].subscription_expiry = (
                self.block_processor.get_block_count() + self.subscription_duration
            )

        self.user_db.store_user(user_id, self.registered_users[user_id].to_dict())
        receipt = create_registration_receipt(
            user_id, self.registered_users[user_id].available_slots, self.registered_users[user_id].subscription_expiry
        )

        return (
            self.registered_users[user_id].available_slots,
            self.registered_users[user_id].subscription_expiry,
            receipt,
        )

    def authenticate_user(self, message, signature):
        """
        Checks if a request comes from a registered user by ec-recovering their public key from a signed message.

        Args:
            message (:obj:`bytes`): byte representation of the original message from where the signature was generated.
            signature (:obj:`str`): the user's signature (hex-encoded).

        Returns:
            :obj:`str`: A compressed key recovered from the signature and matching a registered user.

        Raises:
            :obj:`AuthenticationFailure`: if the user cannot be authenticated.
            :obj:`SubscriptionExpired`: if the subscription has expired.
        """

        try:
            rpk = Cryptographer.recover_pk(message, signature)
            user_id = Cryptographer.get_compressed_pk(rpk)

            if user_id not in self.registered_users:
                raise AuthenticationFailure("User not found.")

            return user_id

        except (InvalidParameter, InvalidKey, SignatureError):
            raise AuthenticationFailure("Wrong message or signature.")

    def check_subscription_expiry(self, user_id):
        """
        Checks if a subscription has expired.

        Args:
            user_id(:obj:`str`): the public key that identifies the user (33-bytes hex str).

        Raises:
            :obj:`SubscriptionExpired`: If the subscription has expired.
        """

        current_height = self.block_processor.get_block_count()
        if current_height > self.registered_users[user_id].subscription_expiry + self.expiry_delta:
            raise SubscriptionExpired(
                f"The subscription expired at {self.registered_users[user_id].subscription_expiry}"
            )

    def add_update_appointment(self, user_id, uuid, ext_appointment):
        """
        Adds (or updates) an appointment to a user subscription. The user slots are updated accordingly.

        Slots are taken if a new appointment is given, or an update is given with an appointment bigger than the
        existing one.

        Slots are given back if an update is given but the new appointment is smaller than the existing one.

        Args:
            user_id (:obj:`str`): the public key that identifies the user (33-bytes hex str).
            uuid (:obj:`str`): the appointment uuid.
            ext_appointment (:obj:`ExtendedAppointment <teos.extended_appointment.ExtendedAppointment>`): the summary of
                new appointment the user is requesting.

        Returns:
            :obj:`int`: The number of remaining appointment slots.

        Raises:
            :obj:`NotEnoughSlots`: if the user does not have enough slots to fill.
        """

        self.lock.acquire()
        # For updates the difference between the existing appointment and the update is computed.
        if uuid in self.registered_users[user_id].appointments:
            used_slots = self.registered_users[user_id].appointments[uuid]

        else:
            # For regular appointments 1 slot is reserved per ENCRYPTED_BLOB_MAX_SIZE_HEX block.
            used_slots = 0

        required_slots = ceil(len(ext_appointment.encrypted_blob) / ENCRYPTED_BLOB_MAX_SIZE_HEX)

        if required_slots - used_slots <= self.registered_users.get(user_id).available_slots:
            # Filling / freeing slots depending on whether this is an update or not, and if it is bigger or smaller than
            # the old appointment.
            self.registered_users.get(user_id).appointments[uuid] = required_slots
            self.registered_users.get(user_id).available_slots -= required_slots - used_slots
            self.user_db.store_user(user_id, self.registered_users[user_id].to_dict())

        else:
            self.lock.release()
            raise NotEnoughSlots()

        self.lock.release()
        return self.registered_users.get(user_id).available_slots

    def get_expired_appointments(self, block_height):
        """
        Gets a list of appointments that expire at a given block height.

        Args:
            block_height: the block height that wants to be checked.

        Returns:
            :obj:`list`: A list of appointment uuids that will expire at ``block_height``.
        """

        expired_appointments = []
        # Avoiding dictionary changed size during iteration
        for user_id in list(self.registered_users.keys()):
            if block_height == self.registered_users[user_id].subscription_expiry + self.expiry_delta:
                expired_appointments.extend(self.registered_users[user_id].appointments)

        return expired_appointments
