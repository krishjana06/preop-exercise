import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import triage_submission
from preop.extraction import DocumentExtraction, Query
from preop.models import PatientSubmission
from preop.semantic import (
    SemanticExtraction,
    apply_grounded_extraction,
    grounded_quote,
    request_extraction,
    resolve_semantics,
)


def semantic_result(**kwargs):
    return SemanticExtraction.model_validate(
        {
            "hp": [],
            "consents": [],
            "medications": [],
            "plans": [],
            "vitals": [],
            **kwargs,
        }
    )


@pytest.mark.parametrize(
    "index,quote,valid",
    [
        (0, "PREOPERATIVE HISTORY AND PHYSICAL", True),
        (0, "invented quote", False),
        (-1, "PREOPERATIVE HISTORY AND PHYSICAL", False),
        (100, "PREOPERATIVE HISTORY AND PHYSICAL", False),
        (0, "", False),
        (0, "   ", False),
    ],
)
def test_exact_quote_grounding(submission, index, quote, valid):
    assert (
        grounded_quote(PatientSubmission.model_validate(submission), index, quote)
        is valid
    )


@pytest.mark.parametrize(
    "quote,accepted",
    [("PREOPERATIVE HISTORY AND PHYSICAL", True), ("Made-up pre-op evaluation", False)],
)
def test_hp_claim_requires_source_quote(submission, quote, accepted):
    data = PatientSubmission.model_validate(submission)
    extraction = DocumentExtraction(queries=[Query(0, "HP")])
    result = semantic_result(
        hp=[
            {
                "document_index": 0,
                "is_preop_hp": True,
                "applies_to_procedure": True,
                "quote": quote,
            }
        ]
    )
    remaining = apply_grounded_extraction(data, extraction, result, extraction.queries)
    assert bool(extraction.hp) is accepted
    assert bool(remaining) is not accepted


def test_out_of_scope_claim_does_not_answer_query(submission):
    extraction = DocumentExtraction(queries=[Query(0, "HP")])
    result = semantic_result(
        hp=[
            {
                "document_index": 1,
                "is_preop_hp": True,
                "applies_to_procedure": True,
                "quote": submission["documents"][1]["text"],
            }
        ]
    )
    assert apply_grounded_extraction(
        PatientSubmission.model_validate(submission),
        extraction,
        result,
        extraction.queries,
    ) == [Query(0, "HP")]
    assert not extraction.hp


def test_plan_requires_separate_grounded_instructions(submission):
    text = "Hold Eliquis before surgery. Resume Eliquis after surgery."
    submission["documents"].append({"date": "2030-06-28", "text": text})
    extraction = DocumentExtraction(queries=[Query(2, "PLAN")])
    result = semantic_result(
        plans=[
            {
                "document_index": 2,
                "is_plan": True,
                "medication_name": "Eliquis",
                "applies_to_procedure": True,
                "preop_instruction_present": True,
                "preop_quote": "Hold Eliquis before surgery.",
                "postop_instruction_present": True,
                "postop_quote": "Invented restart instruction",
                "quote": text,
            }
        ]
    )
    assert apply_grounded_extraction(
        PatientSubmission.model_validate(submission),
        extraction,
        result,
        extraction.queries,
    )
    assert not extraction.plans


def test_vital_numbers_cannot_be_invented_in_real_quote(submission):
    submission["documents"].append(
        {"date": "2030-06-29", "text": "Measured pressure 120 over 80."}
    )
    extraction = DocumentExtraction(queries=[Query(2, "VITAL")])
    result = semantic_result(
        vitals=[
            {
                "document_index": 2,
                "vital_type": "blood_pressure",
                "observed_date": None,
                "observed_time": None,
                "systolic": 190,
                "diastolic": 115,
                "temperature_value": None,
                "temperature_unit": None,
                "quote": "Measured pressure 120 over 80.",
            }
        ]
    )
    assert apply_grounded_extraction(
        PatientSubmission.model_validate(submission),
        extraction,
        result,
        extraction.queries,
    )
    assert not extraction.measurements


def test_grounded_celsius_is_converted_by_code(submission):
    submission["documents"].append({"date": "2030-06-29", "text": "Measured 38.0 C."})
    extraction = DocumentExtraction(queries=[Query(2, "VITAL")])
    result = semantic_result(
        vitals=[
            {
                "document_index": 2,
                "vital_type": "temperature",
                "observed_date": None,
                "observed_time": None,
                "systolic": None,
                "diastolic": None,
                "temperature_value": 38,
                "temperature_unit": "C",
                "quote": "Measured 38.0 C.",
            }
        ]
    )
    assert not apply_grounded_extraction(
        PatientSubmission.model_validate(submission),
        extraction,
        result,
        extraction.queries,
    )
    assert extraction.measurements[0].temperature_f == 100.4


def test_sdk_request_uses_harness_model_and_strict_pydantic(submission, monkeypatch):
    import openai

    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr(openai, "OpenAI", factory)
    client.responses.parse.return_value = SimpleNamespace(
        output_parsed=semantic_result()
    )
    request_extraction(
        PatientSubmission.model_validate(submission),
        [Query(1, "CONSENT")],
        model="selected-model",
    )
    call = client.responses.parse.call_args.kwargs
    assert call["model"] == "selected-model"
    assert call["text_format"] is SemanticExtraction
    assert call["store"] is False
    payload = json.loads(call["input"])
    assert [d["document_index"] for d in payload["documents"]] == [1]
    assert "patient" not in payload and "procedure_risk" not in payload
    assert "Do not decide" in call["instructions"]
    factory.assert_called_once_with(timeout=30.0, max_retries=1)


def test_fallback_only_resends_outstanding_tasks(submission, monkeypatch):
    import preop.semantic as semantic

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    monkeypatch.setenv("PREOP_FALLBACK_MODEL", "fallback-model")
    good_hp = {
        "document_index": 0,
        "is_preop_hp": True,
        "applies_to_procedure": True,
        "quote": submission["documents"][0]["text"],
    }
    bad_consent = {
        "document_index": 1,
        "is_consent": True,
        "applies_to_procedure": True,
        "signature_status": "SIGNED",
        "quote": "fabricated",
    }
    good_consent = {**bad_consent, "quote": submission["documents"][1]["text"]}
    request = Mock(
        side_effect=[
            semantic_result(hp=[good_hp], consents=[bad_consent]),
            semantic_result(consents=[good_consent]),
        ]
    )
    monkeypatch.setattr(semantic, "request_extraction", request)
    extraction = DocumentExtraction(queries=[Query(0, "HP"), Query(1, "CONSENT")])
    resolve_semantics(
        PatientSubmission.model_validate(submission), extraction, model="primary-model"
    )
    assert request.call_args_list[0].kwargs["model"] == "primary-model"
    assert request.call_args_list[1].kwargs["model"] == "fallback-model"
    assert request.call_args_list[1].kwargs["focus"] is True
    assert request.call_args_list[1].args[1] == [Query(1, "CONSENT")]
    assert not extraction.queries


def test_no_fallback_call_after_success(submission, monkeypatch):
    import preop.semantic as semantic

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    monkeypatch.setenv("PREOP_FALLBACK_MODEL", "fallback-model")
    request = Mock(
        return_value=semantic_result(
            hp=[
                {
                    "document_index": 0,
                    "is_preop_hp": False,
                    "applies_to_procedure": None,
                    "quote": submission["documents"][0]["text"],
                }
            ]
        )
    )
    monkeypatch.setattr(semantic, "request_extraction", request)
    resolve_semantics(
        PatientSubmission.model_validate(submission),
        DocumentExtraction(queries=[Query(0, "HP")]),
        model="primary-model",
    )
    assert request.call_count == 1


def test_no_client_needed_for_deterministic_input(submission, monkeypatch):
    import preop.semantic as semantic

    request = Mock(side_effect=AssertionError("No model needed"))
    monkeypatch.setattr(semantic, "request_extraction", request)
    assert triage_submission(submission, model="primary-model").decision == "READY"
    request.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("invalid structured output"),
        RuntimeError("unexpected programming bug"),
    ],
)
def test_expected_api_failure_is_uncertainty_programming_bugs_propagate(
    submission, monkeypatch, failure
):
    import preop.semantic as semantic

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    submission["documents"][0]["text"] = "History and physical completed."
    monkeypatch.setattr(semantic, "request_extraction", Mock(side_effect=failure))
    if isinstance(failure, RuntimeError):
        with pytest.raises(RuntimeError):
            triage_submission(submission, model="primary-model")
    else:
        output = triage_submission(submission, model="primary-model")
        assert output.decision == "NEEDS_FOLLOW_UP"
        assert any(i.category == "MISSING_REQUIRED_DATA" for i in output.issues)


def test_semantic_schema_has_no_policy_decision():
    schema = SemanticExtraction.model_json_schema()
    assert "decision" not in schema["properties"]
    assert schema["additionalProperties"] is False
    for definition in schema["$defs"].values():
        assert definition["additionalProperties"] is False
        assert set(definition["required"]) == set(definition["properties"])


def test_failed_sibling_cannot_hide_behind_grounded_positive(submission):
    extraction = DocumentExtraction(queries=[Query(0, "HP")])
    result = semantic_result(
        hp=[
            {
                "document_index": 0,
                "is_preop_hp": True,
                "applies_to_procedure": True,
                "quote": submission["documents"][0]["text"],
            },
            {
                "document_index": 0,
                "is_preop_hp": True,
                "applies_to_procedure": True,
                "quote": "fabricated extra claim",
            },
        ]
    )
    assert apply_grounded_extraction(
        PatientSubmission.model_validate(submission),
        extraction,
        result,
        extraction.queries,
    )
    assert not extraction.hp


def test_fallback_payload_contains_only_relevant_contiguous_excerpts(
    submission, monkeypatch
):
    import openai

    client = Mock()
    monkeypatch.setattr(openai, "OpenAI", Mock(return_value=client))
    client.responses.parse.return_value = SimpleNamespace(
        output_parsed=semantic_result()
    )
    request_extraction(
        PatientSubmission.model_validate(submission),
        [Query(1, "CONSENT")],
        model="fallback-model",
        focus=True,
    )
    doc = json.loads(client.responses.parse.call_args.kwargs["input"])["documents"][0]
    assert "text" not in doc
    assert all(
        excerpt in submission["documents"][1]["text"] for excerpt in doc["excerpts"]
    )


def test_conflicting_grounded_document_claims_remain_unknown(submission):
    extraction = DocumentExtraction(queries=[Query(0, "HP")])
    result = semantic_result(
        hp=[
            {
                "document_index": 0,
                "is_preop_hp": True,
                "applies_to_procedure": True,
                "quote": submission["documents"][0]["text"],
            },
            {
                "document_index": 0,
                "is_preop_hp": False,
                "applies_to_procedure": False,
                "quote": "History and exam completed for planned procedure.",
            },
        ]
    )
    assert apply_grounded_extraction(
        PatientSubmission.model_validate(submission),
        extraction,
        result,
        extraction.queries,
    )
    assert not extraction.hp


def test_both_api_routes_failing_cannot_return_ready(submission, monkeypatch):
    from openai import APIConnectionError

    import preop.semantic as semantic

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    monkeypatch.setenv("PREOP_FALLBACK_MODEL", "fallback-model")
    submission["documents"][0]["text"] = "History and physical completed."
    request = Mock(side_effect=APIConnectionError(request=Mock()))
    monkeypatch.setattr(semantic, "request_extraction", request)
    assert (
        triage_submission(submission, model="primary-model").decision
        == "NEEDS_FOLLOW_UP"
    )
    assert request.call_count == 2


def test_grounded_initial_reading_cannot_hide_unparsed_recheck(submission):
    from preop.extraction import extract_documents

    submission["documents"].append(
        {"date": "2030-06-29", "text": "08:00 BP 120/80.\n08:30 BP was 190 over 115."}
    )
    data = PatientSubmission.model_validate(submission)
    extraction = extract_documents(data)
    result = semantic_result(
        vitals=[
            {
                "document_index": 2,
                "vital_type": "blood_pressure",
                "observed_date": None,
                "observed_time": None,
                "systolic": 120,
                "diastolic": 80,
                "temperature_value": None,
                "temperature_unit": None,
                "quote": "BP 120/80",
            }
        ]
    )
    assert apply_grounded_extraction(data, extraction, result, extraction.queries) == [
        Query(2, "VITAL")
    ]


def test_quote_numeric_grounding_checks_decimal_value(submission):
    submission["documents"].append({"date": "2030-06-29", "text": "Measured 38.6 C."})
    extraction = DocumentExtraction(queries=[Query(2, "VITAL")])
    result = semantic_result(
        vitals=[
            {
                "document_index": 2,
                "vital_type": "temperature",
                "observed_date": None,
                "observed_time": None,
                "systolic": None,
                "diastolic": None,
                "temperature_value": 38,
                "temperature_unit": "C",
                "quote": "Measured 38.6 C.",
            }
        ]
    )
    assert apply_grounded_extraction(
        PatientSubmission.model_validate(submission),
        extraction,
        result,
        extraction.queries,
    )
    assert not extraction.measurements
