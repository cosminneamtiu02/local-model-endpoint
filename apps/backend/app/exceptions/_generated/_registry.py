"""Generated error registry. Do not edit.

Maps SCREAMING_SNAKE error codes to their concrete DomainError
subclasses. The mapping is the planned consumer-facing reverse-
lookup surface for cases where an error code arrives as a string
(e.g. a future relay/proxy endpoint that accepts an upstream
consumer's typed error code and re-raises a matching DomainError
into our handler chain). Production app/ code that raises typed
errors from explicit class names does NOT consume this registry —
the test backstop in tests/unit/exceptions/test_registry.py is
the current sole consumer, pinning the dict shape so the codegen
stays canonical until the runtime consumer lands.
"""

from app.exceptions._generated.adapter_connection_failure_error import AdapterConnectionFailureError
from app.exceptions._generated.conflict_error import ConflictError
from app.exceptions._generated.inference_timeout_error import InferenceTimeoutError
from app.exceptions._generated.internal_error import InternalError
from app.exceptions._generated.method_not_allowed_error import MethodNotAllowedError
from app.exceptions._generated.model_capability_not_supported_error import (
    ModelCapabilityNotSupportedError,
)
from app.exceptions._generated.not_found_error import NotFoundError
from app.exceptions._generated.queue_full_error import QueueFullError
from app.exceptions._generated.rate_limited_error import RateLimitedError
from app.exceptions._generated.registry_not_found_error import RegistryNotFoundError
from app.exceptions._generated.validation_failed_error import ValidationFailedError
from app.exceptions.base import DomainError

ERROR_CLASSES: dict[str, type[DomainError]] = {
    "ADAPTER_CONNECTION_FAILURE": AdapterConnectionFailureError,
    "CONFLICT": ConflictError,
    "INFERENCE_TIMEOUT": InferenceTimeoutError,
    "INTERNAL_ERROR": InternalError,
    "METHOD_NOT_ALLOWED": MethodNotAllowedError,
    "MODEL_CAPABILITY_NOT_SUPPORTED": ModelCapabilityNotSupportedError,
    "NOT_FOUND": NotFoundError,
    "QUEUE_FULL": QueueFullError,
    "RATE_LIMITED": RateLimitedError,
    "REGISTRY_NOT_FOUND": RegistryNotFoundError,
    "VALIDATION_FAILED": ValidationFailedError,
}
