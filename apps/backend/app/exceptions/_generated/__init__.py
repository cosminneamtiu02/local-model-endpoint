"""Generated error classes. Do not edit."""

from app.exceptions._generated.adapter_connection_failure_error import AdapterConnectionFailureError
from app.exceptions._generated.adapter_connection_failure_params import (
    AdapterConnectionFailureParams,
)
from app.exceptions._generated.conflict_error import ConflictError
from app.exceptions._generated.inference_timeout_error import InferenceTimeoutError
from app.exceptions._generated.inference_timeout_params import InferenceTimeoutParams
from app.exceptions._generated.internal_error import InternalError
from app.exceptions._generated.method_not_allowed_error import MethodNotAllowedError
from app.exceptions._generated.model_capability_not_supported_error import (
    ModelCapabilityNotSupportedError,
)
from app.exceptions._generated.model_capability_not_supported_params import (
    ModelCapabilityNotSupportedParams,
)
from app.exceptions._generated.not_found_error import NotFoundError
from app.exceptions._generated.queue_full_error import QueueFullError
from app.exceptions._generated.queue_full_params import QueueFullParams
from app.exceptions._generated.rate_limited_error import RateLimitedError
from app.exceptions._generated.rate_limited_params import RateLimitedParams
from app.exceptions._generated.registry_not_found_error import RegistryNotFoundError
from app.exceptions._generated.registry_not_found_params import RegistryNotFoundParams
from app.exceptions._generated.validation_failed_error import ValidationFailedError
from app.exceptions._generated.validation_failed_params import ValidationFailedParams
from app.exceptions._generated._registry import ERROR_CLASSES

__all__ = [
    "ERROR_CLASSES",
    "AdapterConnectionFailureError",
    "AdapterConnectionFailureParams",
    "ConflictError",
    "InferenceTimeoutError",
    "InferenceTimeoutParams",
    "InternalError",
    "MethodNotAllowedError",
    "ModelCapabilityNotSupportedError",
    "ModelCapabilityNotSupportedParams",
    "NotFoundError",
    "QueueFullError",
    "QueueFullParams",
    "RateLimitedError",
    "RateLimitedParams",
    "RegistryNotFoundError",
    "RegistryNotFoundParams",
    "ValidationFailedError",
    "ValidationFailedParams",
]
