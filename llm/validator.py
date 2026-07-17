from __future__ import annotations

from dataclasses import dataclass

from llm import schema


@dataclass
class ValidationResult:
    valid: bool
    error_message: str = ""


def _missing_keys(value: dict, required: set[str], path: str) -> str:
    missing = sorted(required - set(value))
    if missing:
        return f"{path} missing required fields: {', '.join(missing)}"
    return ""


def _enum(value: object, allowed: set[str], path: str) -> str:
    if value not in allowed:
        return f"{path} has invalid value: {value!r}"
    return ""


class LLMResultValidator:
    def validate(self, result_json: dict, original_text: str) -> ValidationResult:
        if not isinstance(result_json, dict):
            return ValidationResult(False, "LLM result is not a JSON object")

        error = _missing_keys(result_json, schema.REQUIRED_TOP_LEVEL_FIELDS, "root")
        if error:
            return ValidationResult(False, error)

        for path, expected_type in (
            ("valid_review", bool),
            ("purchase_decision_evidence", dict),
            ("praise_items", list),
            ("complaint_items", list),
            ("noise_flags", dict),
        ):
            if not isinstance(result_json.get(path), expected_type):
                return ValidationResult(False, f"{path} must be {expected_type.__name__}")

        for error in (
            _enum(result_json.get("overall_sentiment"), schema.OVERALL_SENTIMENTS, "overall_sentiment"),
            _enum(result_json.get("main_target"), schema.TARGETS, "main_target"),
        ):
            if error:
                return ValidationResult(False, error)

        purchase = result_json["purchase_decision_evidence"]
        error = _missing_keys(purchase, schema.REQUIRED_PURCHASE_FIELDS, "purchase_decision_evidence")
        if error:
            return ValidationResult(False, error)
        if not isinstance(purchase.get("is_purchase_decision_evidence"), bool):
            return ValidationResult(False, "purchase_decision_evidence.is_purchase_decision_evidence must be bool")
        error = _enum(purchase.get("evidence_level"), schema.EVIDENCE_LEVELS, "purchase_decision_evidence.evidence_level")
        if error:
            return ValidationResult(False, error)

        noise = result_json["noise_flags"]
        error = _missing_keys(noise, schema.REQUIRED_NOISE_FIELDS, "noise_flags")
        if error:
            return ValidationResult(False, error)
        for key in schema.REQUIRED_NOISE_FIELDS:
            if not isinstance(noise.get(key), bool):
                return ValidationResult(False, f"noise_flags.{key} must be bool")

        for index, item in enumerate(result_json["praise_items"]):
            error = self._validate_praise_item(item, index, original_text)
            if error:
                return ValidationResult(False, error)

        for index, item in enumerate(result_json["complaint_items"]):
            error = self._validate_complaint_item(item, index, original_text)
            if error:
                return ValidationResult(False, error)

        return ValidationResult(True)

    def _validate_quote(self, item: dict, path: str, original_text: str) -> str:
        quote = str(item.get("evidence_quote", "")).strip()
        if not quote:
            return f"{path}.evidence_quote is empty"
        if quote not in (original_text or ""):
            return f"{path}.evidence_quote is not a substring of the original review"
        return ""

    def _validate_praise_item(self, item: object, index: int, original_text: str) -> str:
        path = f"praise_items[{index}]"
        if not isinstance(item, dict):
            return f"{path} must be object"
        error = _missing_keys(item, schema.REQUIRED_PRAISE_FIELDS, path)
        if error:
            return error
        checks = (
            _enum(item.get("target"), schema.TARGETS, f"{path}.target"),
            _enum(item.get("praise_family"), schema.PRAISE_FAMILIES, f"{path}.praise_family"),
            _enum(item.get("praise_method"), schema.PRAISE_METHODS, f"{path}.praise_method"),
            _enum(item.get("evidence_strength"), schema.EVIDENCE_LEVELS, f"{path}.evidence_strength"),
            _enum(item.get("business_value"), schema.BUSINESS_VALUES, f"{path}.business_value"),
            self._validate_quote(item, path, original_text),
        )
        return next((error for error in checks if error), "")

    def _validate_complaint_item(self, item: object, index: int, original_text: str) -> str:
        path = f"complaint_items[{index}]"
        if not isinstance(item, dict):
            return f"{path} must be object"
        error = _missing_keys(item, schema.REQUIRED_COMPLAINT_FIELDS, path)
        if error:
            return error
        checks = (
            _enum(item.get("target"), schema.TARGETS, f"{path}.target"),
            _enum(item.get("complaint_family"), schema.COMPLAINT_FAMILIES, f"{path}.complaint_family"),
            _enum(item.get("complaint_method"), schema.COMPLAINT_METHODS, f"{path}.complaint_method"),
            _enum(item.get("evidence_strength"), schema.EVIDENCE_LEVELS, f"{path}.evidence_strength"),
            _enum(item.get("severity"), schema.SEVERITIES, f"{path}.severity"),
            _enum(item.get("fixability"), schema.FIXABILITIES, f"{path}.fixability"),
            self._validate_quote(item, path, original_text),
        )
        return next((error for error in checks if error), "")

