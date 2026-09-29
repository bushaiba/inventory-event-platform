class InventoryPlatformError(Exception):
    pass


class NotFoundError(InventoryPlatformError):
    pass


class ConflictError(InventoryPlatformError):
    pass


class ValidationError(InventoryPlatformError):
    pass
