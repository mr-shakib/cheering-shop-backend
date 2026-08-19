"""Enum types.

`native_enum=True` with `create_type=False`: the types are created by migration
0001, so the ORM must reference them without trying to re-create them.
"""

import enum

from sqlalchemy.dialects.postgresql import ENUM


class UserRole(enum.StrEnum):
    CUSTOMER = "CUSTOMER"
    VENDOR = "VENDOR"
    RIDER = "RIDER"
    ADMIN = "ADMIN"


class AddressType(enum.StrEnum):
    HOME = "HOME"
    WORK = "WORK"
    OTHER = "OTHER"


class RestaurantStatus(enum.StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OrderStatus(enum.StrEnum):
    PENDING = "PENDING"
    PREPARING = "PREPARING"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PaymentMethod(enum.StrEnum):
    COD = "COD"
    WALLET = "WALLET"
    BKASH = "BKASH"
    CARD = "CARD"


class PaymentStatus(enum.StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class OtpPurpose(enum.StrEnum):
    SIGNUP = "SIGNUP"
    LOGIN = "LOGIN"
    PASSWORD_RESET = "PASSWORD_RESET"


class DiscountType(enum.StrEnum):
    PERCENTAGE = "PERCENTAGE"
    FIXED = "FIXED"
    FREE_DELIVERY = "FREE_DELIVERY"


class DevicePlatform(enum.StrEnum):
    IOS = "IOS"
    ANDROID = "ANDROID"
    WEB = "WEB"


class BiometricAlgorithm(enum.StrEnum):
    ES256 = "ES256"      # ECDSA P-256 + SHA-256 — iOS Secure Enclave
    ED25519 = "ED25519"  # Android Keystore / software keys


class ActorType(enum.StrEnum):
    CUSTOMER = "CUSTOMER"
    VENDOR = "VENDOR"
    RIDER = "RIDER"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"


class VendorApplicationStatus(enum.StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PayoutMethod(enum.StrEnum):
    BANK = "BANK"
    BKASH = "BKASH"
    NAGAD = "NAGAD"
    ROCKET = "ROCKET"


class PayoutStatus(enum.StrEnum):
    PROCESSING = "PROCESSING"  # requested; awaiting the transfer being made
    COMPLETED = "COMPLETED"    # money confirmed sent
    FAILED = "FAILED"          # transfer failed; the amount returns to balance


def pg_enum(py_enum: type[enum.Enum], name: str) -> ENUM:
    return ENUM(
        py_enum, name=name, create_type=False, values_callable=lambda e: [m.value for m in e]
    )


UserRoleType = pg_enum(UserRole, "user_role")
AddressTypeType = pg_enum(AddressType, "address_type")
RestaurantStatusType = pg_enum(RestaurantStatus, "restaurant_status")
OrderStatusType = pg_enum(OrderStatus, "order_status")
PaymentMethodType = pg_enum(PaymentMethod, "payment_method")
PaymentStatusType = pg_enum(PaymentStatus, "payment_status")
OtpPurposeType = pg_enum(OtpPurpose, "otp_purpose")
DiscountTypeType = pg_enum(DiscountType, "discount_type")
DevicePlatformType = pg_enum(DevicePlatform, "device_platform")
ActorTypeType = pg_enum(ActorType, "actor_type")
BiometricAlgorithmType = pg_enum(BiometricAlgorithm, "biometric_algorithm")
VendorApplicationStatusType = pg_enum(VendorApplicationStatus, "vendor_application_status")
PayoutMethodType = pg_enum(PayoutMethod, "payout_method")
PayoutStatusType = pg_enum(PayoutStatus, "payout_status")

# Order states in which a customer may still cancel (spec §4).
CANCELLABLE_STATUSES = {OrderStatus.PENDING}

# The lifecycle from spec §8. Used by the service layer to reject illegal jumps
# such as PENDING -> DELIVERED, which the database itself will happily accept.
ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY, OrderStatus.CANCELLED},
    OrderStatus.READY: {OrderStatus.PICKED_UP, OrderStatus.CANCELLED},
    OrderStatus.PICKED_UP: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}
