import pytest

import common.errors as errors
from common.constants import LOCATOR_LEN_BYTES, LOCATOR_LEN_HEX

from test.teos.conftest import config
from teos.inspector import Inspector, InspectionFailed
from test.teos.unit.conftest import get_random_value_hex

NO_HEX_STRINGS = [
    "R" * LOCATOR_LEN_HEX,
    get_random_value_hex(LOCATOR_LEN_BYTES - 1) + "PP",
    "$" * LOCATOR_LEN_HEX,
    " " * LOCATOR_LEN_HEX,
]
WRONG_TYPES = [
    [],
    "",
    get_random_value_hex(LOCATOR_LEN_BYTES),
    3.2,
    2.0,
    (),
    object,
    {},
    " " * LOCATOR_LEN_HEX,
    object(),
]
WRONG_TYPES_NO_STR = [[], bytes.fromhex(get_random_value_hex(LOCATOR_LEN_BYTES)), 3.2, 2.0, (), object, {}, object()]

MIN_TO_SELF_DELAY = config.get("MIN_TO_SELF_DELAY")


@pytest.fixture(scope="module")
def inspector():
    return Inspector(MIN_TO_SELF_DELAY)


def test_check_locator(inspector):
    # Right appointment type, size and format
    locator = get_random_value_hex(LOCATOR_LEN_BYTES)
    assert inspector.check_locator(locator) is None

    # Wrong size (too big)
    locator = get_random_value_hex(LOCATOR_LEN_BYTES + 1)
    with pytest.raises(InspectionFailed):
        try:
            inspector.check_locator(locator)

        except InspectionFailed as e:
            assert e.errno == errors.APPOINTMENT_WRONG_FIELD_SIZE
            raise e

    # Wrong size (too small)
    locator = get_random_value_hex(LOCATOR_LEN_BYTES - 1)
    with pytest.raises(InspectionFailed):
        try:
            inspector.check_locator(locator)

        except InspectionFailed as e:
            assert e.errno == errors.APPOINTMENT_WRONG_FIELD_SIZE
            raise e

    # Empty
    locator = None
    with pytest.raises(InspectionFailed):
        try:
            inspector.check_locator(locator)

        except InspectionFailed as e:
            assert e.errno == errors.APPOINTMENT_EMPTY_FIELD
            raise e

    # Wrong type (several types tested, it should do for anything that is not a string)
    locators = [[], -1, 3.2, 0, 4, (), object, {}, object()]

    for locator in locators:
        with pytest.raises(InspectionFailed):
            try:
                inspector.check_locator(locator)

            except InspectionFailed as e:
                assert e.errno == errors.APPOINTMENT_WRONG_FIELD_TYPE
                raise e

    # Wrong format (no hex)
    locators = NO_HEX_STRINGS
    for locator in locators:
        with pytest.raises(InspectionFailed):
            try:
                inspector.check_locator(locator)

            except InspectionFailed as e:
                assert e.errno == errors.APPOINTMENT_WRONG_FIELD_FORMAT
                raise e


def test_check_to_self_delay(inspector):
    # Right value, right format
    to_self_delays = [MIN_TO_SELF_DELAY, MIN_TO_SELF_DELAY + 1, MIN_TO_SELF_DELAY + 1000]
    for to_self_delay in to_self_delays:
        assert inspector.check_to_self_delay(to_self_delay) is None

    # to_self_delay too small
    to_self_delays = [MIN_TO_SELF_DELAY - 1, MIN_TO_SELF_DELAY - 2, 0, -1, -1000]
    for to_self_delay in to_self_delays:
        with pytest.raises(InspectionFailed):
            try:
                inspector.check_to_self_delay(to_self_delay)

            except InspectionFailed as e:
                assert e.errno == errors.APPOINTMENT_FIELD_TOO_SMALL
                raise e

    # Empty field
    to_self_delay = None
    with pytest.raises(InspectionFailed):
        try:
            inspector.check_to_self_delay(to_self_delay)

        except InspectionFailed as e:
            assert e.errno == errors.APPOINTMENT_EMPTY_FIELD
            raise e

    # Wrong data type
    to_self_delays = WRONG_TYPES
    for to_self_delay in to_self_delays:
        with pytest.raises(InspectionFailed):
            try:
                inspector.check_to_self_delay(to_self_delay)

            except InspectionFailed as e:
                assert e.errno == errors.APPOINTMENT_WRONG_FIELD_TYPE
                raise e


def test_check_blob(inspector):
    # Right format and length
    encrypted_blob = get_random_value_hex(120)
    assert inspector.check_blob(encrypted_blob) is None

    # Wrong type
    encrypted_blobs = WRONG_TYPES_NO_STR
    for encrypted_blob in encrypted_blobs:
        with pytest.raises(InspectionFailed):
            try:
                inspector.check_blob(encrypted_blob)

            except InspectionFailed as e:
                assert e.errno == errors.APPOINTMENT_WRONG_FIELD_TYPE
                raise e

    # Empty field
    encrypted_blob = None
    with pytest.raises(InspectionFailed):
        try:
            inspector.check_blob(encrypted_blob)

        except InspectionFailed as e:
            assert e.errno == errors.APPOINTMENT_EMPTY_FIELD
            raise e

    # Wrong format (no hex)
    encrypted_blobs = NO_HEX_STRINGS
    for encrypted_blob in encrypted_blobs:
        with pytest.raises(InspectionFailed):
            try:
                inspector.check_blob(encrypted_blob)

            except InspectionFailed as e:
                assert e.errno == errors.APPOINTMENT_WRONG_FIELD_FORMAT
                raise e


def test_inspect(inspector):
    # Valid appointment
    locator = get_random_value_hex(LOCATOR_LEN_BYTES)
    to_self_delay = MIN_TO_SELF_DELAY
    encrypted_blob = get_random_value_hex(64)

    appointment_data = {"locator": locator, "to_self_delay": to_self_delay, "encrypted_blob": encrypted_blob}

    appointment = inspector.inspect(appointment_data)

    assert (
        appointment.locator == locator
        and appointment.to_self_delay == to_self_delay
        and appointment.encrypted_blob == encrypted_blob
    )


def test_inspect_wrong(inspector):
    # Wrong types (taking out empty dict, since that's a different error)
    wrong_types = WRONG_TYPES.pop(WRONG_TYPES.index({}))
    for data in wrong_types:
        with pytest.raises(InspectionFailed):
            try:
                inspector.inspect(data)
            except InspectionFailed as e:
                print(data)
                assert e.errno == errors.APPOINTMENT_WRONG_FIELD
                raise e

    # None data
    with pytest.raises(InspectionFailed):
        try:
            inspector.inspect(None)
        except InspectionFailed as e:
            assert e.errno == errors.APPOINTMENT_EMPTY_FIELD
            raise e
