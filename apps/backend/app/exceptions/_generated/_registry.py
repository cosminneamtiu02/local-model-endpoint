"""Generated error registry. Do not edit."""

from app.exceptions.base import DomainError
from app.exceptions._generated.adapter_connection_failure_error import AdapterConnectionFailureError
from app.exceptions._generated.conflict_error import ConflictError
from app.exceptions._generated.http_error import HttpError
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

ERROR_CLASSES: dict[str, type[DomainError]] = {
    "ADAPTER_CONNECTION_FAILURE": AdapterConnectionFailureError,
    "CONFLICT": ConflictError,
    "HTTP_ERROR": HttpError,
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
