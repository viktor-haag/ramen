import pytest

from app.llm.base import LLMResult
from app.models import UserProfile
from app.services import user_profile
from test_profile_docs import add_config, post

GOOD = "\n\n".join(f"{h}\ncontent" for h in user_profile.HEADINGS)


class Fake:
    calls: list = []
    replies: list = []
    on_call = None


@pytest.fixture
def llm(client, monkeypatch):
    Fake.calls = []
    Fake.on_call = None
    Fake.replies = [LLMResult(GOOD, 100, 50, False)]

    class Client:
        def __init__(self, cfg):
            pass

        def complete(self, system, messages, *, json_schema=None, max_tokens=4096):
            Fake.calls.append((system, messages))
            if Fake.on_call:
                Fake.on_call()
            return Fake.replies.pop(0) if len(Fake.replies) > 1 else Fake.replies[0]

    monkeypatch.setattr("app.llm.runner.make_client", lambda cfg, **_: Client(cfg))
    add_config(client)
    return Fake


def prompt_of(call):
    return call[1][0].parts[0]


def put_text(client, text):
    r = client.put("/api/me/profile/free-text", json={"free_text": text})
    assert r.status_code == 200
    return r.json()


def test_get_empty_profile(client):
    body = client.get("/api/me/profile").json()
    assert body == {
        "free_text": None, "profile_markdown": None, "generated_at": None,
        "edited_since_generation": False, "inputs_changed_since_generation": False,
        "version": 0, "documents_used": 0, "documents_unused": 0,
    }


def test_free_text_sets_inputs_changed_only_on_change(client, app):
    body = put_text(client, "  Prefer remote  ")
    assert body["free_text"] == "Prefer remote" and body["inputs_changed_since_generation"] is True
    with app.state.session_factory() as s:
        s.get(UserProfile, 1).inputs_changed_since_generation = False
        s.commit()
    assert put_text(client, "Prefer remote")["inputs_changed_since_generation"] is False  # autosave of same text
    assert put_text(client, "")["free_text"] is None


def test_markdown_edit_versions_and_flags(client):
    body = client.put("/api/me/profile/markdown", json={"profile_markdown": "# mine"}).json()
    assert body["profile_markdown"] == "# mine" and body["version"] == 1 and body["edited_since_generation"] is True
    assert body["inputs_changed_since_generation"] is False
    assert client.put("/api/me/profile/markdown", json={"profile_markdown": "# mine"}).json()["version"] == 1
    assert client.put("/api/me/profile/markdown", json={"profile_markdown": "# more"}).json()["version"] == 2


def test_generate_without_inputs_is_profile_missing(client, llm):
    r = client.post("/api/me/profile/generate")
    assert r.status_code == 409 and r.json()["code"] == "profile_missing"
    assert llm.calls == []
    post(client, "empty.txt", b"   ")  # unusable document does not count
    assert client.post("/api/me/profile/generate").json()["code"] == "profile_missing"


def test_prompt_has_only_usable_documents_and_free_text(client, llm):
    post(client, "cv.txt", b"Ten years of Python", "My CV")
    post(client, "blank.txt", b"")
    post(client, "scan.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20, "unreadable scan")
    put_text(client, "No night shifts")
    r = client.post("/api/me/profile/generate")
    assert r.status_code == 200, r.text
    system, [msg] = llm.calls[-1]
    prompt = msg.parts[0]
    assert "cv.txt" in prompt and "My CV" in prompt and "Ten years of Python" in prompt
    assert "No night shifts" in prompt and "blank.txt" not in prompt and "scan.png" not in prompt
    for heading in user_profile.HEADINGS:
        assert heading in system
    assert "None stated" in system and "majority" in system and "invent" in system
    body = r.json()
    assert body["profile"]["documents_used"] == 1 and body["profile"]["documents_unused"] == 2


def test_generate_flags_and_version(client, llm):
    put_text(client, "notes")
    body = client.post("/api/me/profile/generate").json()
    profile = body["profile"]
    assert profile["profile_markdown"] == GOOD and profile["version"] == 1 and profile["generated_at"]
    assert profile["edited_since_generation"] is False and profile["inputs_changed_since_generation"] is False
    assert body["limit_exceeded"] is False
    put_text(client, "more notes")
    assert client.get("/api/me/profile").json()["inputs_changed_since_generation"] is True
    assert client.post("/api/me/profile/generate").json()["profile"]["version"] == 2
    assert client.get("/api/llm/usage").json()["today"]["input_tokens"] == 200  # purpose profile, recorded


def test_overwrite_guard(client, llm):
    put_text(client, "notes")
    client.post("/api/me/profile/generate")
    client.put("/api/me/profile/markdown", json={"profile_markdown": "my own"})
    n = len(llm.calls)
    r = client.post("/api/me/profile/generate")
    assert r.status_code == 409 and r.json()["code"] == "profile_edited" and len(llm.calls) == n
    assert client.get("/api/me/profile").json()["profile_markdown"] == "my own"
    body = client.post("/api/me/profile/generate?overwrite=true").json()["profile"]
    assert body["profile_markdown"] == GOOD and body["edited_since_generation"] is False and body["version"] == 3


def test_missing_headings_retry_succeeds(client, llm):
    put_text(client, "notes")
    llm.replies = [LLMResult("## Summary\nonly", 10, 5, False), LLMResult(GOOD, 20, 5, False)]
    body = client.post("/api/me/profile/generate").json()
    assert body["profile"]["profile_markdown"] == GOOD
    assert len(llm.calls) == 2
    roles = [m.role for m in llm.calls[1][1]]
    assert roles == ["user", "assistant", "user"]
    correction = llm.calls[1][1][2].parts[0]
    named = correction.split("missing required headings: ")[1].split(". Answer again")[0]
    assert named == ", ".join(h for h in user_profile.HEADINGS if h != "## Summary")
    assert client.get("/api/llm/usage").json()["today"]["input_tokens"] == 30  # both calls recorded


def test_missing_headings_twice_is_invalid_output(client, llm):
    put_text(client, "notes")
    llm.replies = [LLMResult("nope", 10, 5, False)]
    r = client.post("/api/me/profile/generate")
    assert r.status_code == 502 and r.json()["code"] == "llm_invalid_output" and len(llm.calls) == 2
    assert client.get("/api/llm/usage").json()["today"]["input_tokens"] == 20  # both calls recorded
    profile = client.get("/api/me/profile").json()
    assert profile["profile_markdown"] is None and profile["version"] == 0


def test_limit_exceeded_passthrough(client, llm):
    assert client.put("/api/settings", json={
        "fit_auto": False, "fit_concurrency": 2, "daily_limit_kind": "tokens", "daily_limit_value": 10}).status_code == 200
    put_text(client, "notes")
    r = client.post("/api/me/profile/generate")
    assert r.status_code == 200 and r.json()["limit_exceeded"] is True


def test_truncate_texts_longest_first():
    assert user_profile.truncate_texts(["a" * 10, "b" * 20], cap=100) == [10, 20]
    assert user_profile.truncate_texts(["a" * 10, "b" * 500, "c" * 500], cap=110) == [10, 50, 50]
    limits = user_profile.truncate_texts(["a" * 70_000, "b" * 70_000, "c" * 100])
    assert limits[2] == 100 and sum(limits) <= 100_000


def test_prompt_truncates_long_documents_with_note(client, llm):
    post(client, "short.txt", b"short text")
    post(client, "big1.txt", b"x" * 90_000)
    post(client, "big2.txt", b"y" * 90_000)
    assert client.post("/api/me/profile/generate").status_code == 200
    prompt = prompt_of(llm.calls[-1])
    assert "short text" in prompt and "[Truncated:" in prompt and prompt.count("[Truncated:") == 2
    big1 = prompt.split("### Document: big1.txt")[1].split("### Document: big2.txt")[0]
    big2 = prompt.split("### Document: big2.txt")[1]
    assert len(big1.split()[0]) == len(big2.split()[0]) and 49_000 <= len(big1.split()[0]) <= 50_000


def test_fenced_answer_is_stored_without_fences(client, llm):
    put_text(client, "notes")
    llm.replies = [LLMResult("```markdown\n" + GOOD + "\n```", 10, 5, False)]
    assert client.post("/api/me/profile/generate").json()["profile"]["profile_markdown"] == GOOD
    assert len(llm.calls) == 1


def test_preamble_is_removed(client, llm):
    put_text(client, "notes")
    llm.replies = [LLMResult("Sure! Here is your profile:\n\n" + GOOD, 10, 5, False)]
    assert client.post("/api/me/profile/generate").json()["profile"]["profile_markdown"] == GOOD


def test_tolerant_headings_are_canonicalised(client, llm):
    put_text(client, "notes")
    sloppy = GOOD.replace("## Summary", "##summary").replace("## Core skills", "### Core Skills  ")
    sloppy = sloppy.replace("## Education", "**## Education**").replace("## Languages", "## **Languages**")
    llm.replies = [LLMResult(sloppy, 10, 5, False)]
    assert client.post("/api/me/profile/generate").json()["profile"]["profile_markdown"] == GOOD
    assert len(llm.calls) == 1


def test_normalise_markdown_unit():
    assert user_profile.normalise_markdown("no headings") == "no headings"
    assert user_profile.missing_headings(user_profile.normalise_markdown("x\n## summary\nfoo")) == list(
        user_profile.HEADINGS[1:])


def test_edit_during_generation_is_not_overwritten(client, llm):
    put_text(client, "notes")
    llm.on_call = lambda: client.put("/api/me/profile/markdown", json={"profile_markdown": "typed meanwhile"})
    r = client.post("/api/me/profile/generate?overwrite=true")
    assert r.status_code == 409 and r.json()["code"] == "profile_edited"
    assert client.get("/api/me/profile").json()["profile_markdown"] == "typed meanwhile"


@pytest.mark.parametrize("change", ["free_text", "upload", "delete"])
def test_inputs_changed_during_generation_keep_flag(client, llm, change):
    doc = post(client, "cv.txt", b"Python").json()
    put_text(client, "notes")
    actions = {
        "free_text": lambda: put_text(client, "changed notes"),
        "upload": lambda: post(client, "more.txt", b"More"),
        "delete": lambda: client.delete(f"/api/me/documents/{doc['id']}"),
    }
    llm.on_call = actions[change]
    body = client.post("/api/me/profile/generate").json()["profile"]
    assert body["profile_markdown"] == GOOD and body["version"] == 1
    assert body["inputs_changed_since_generation"] is True and body["edited_since_generation"] is False


def test_prompt_states_honesty_and_language_rules(client, llm):
    put_text(client, "Notes in German")
    client.post("/api/me/profile/generate")
    system = llm.calls[-1][0]
    assert "Do not embellish or overstate: no inflated seniority, proficiency or impact." in system
    assert "if there are no documents, use the language of the notes" in system


def test_fresh_install_noop_free_text_sets_no_flag(client):
    assert put_text(client, None)["inputs_changed_since_generation"] is False
    assert put_text(client, "  ")["inputs_changed_since_generation"] is False


def test_free_text_limit(client):
    assert client.put("/api/me/profile/free-text", json={"free_text": "x" * 20_001}).status_code == 422
    assert client.put("/api/me/profile/free-text", json={"free_text": "x" * 20_000}).status_code == 200


def test_subheading_named_like_a_section_is_preserved():
    text = GOOD.replace("## Experience\ncontent", "## Experience\n### Summary\nProject summary")
    out = user_profile.normalise_markdown(text)
    assert out == text
    assert out.splitlines().count("## Summary") == 1 and "### Summary" in out


def test_headings_inside_code_blocks_are_untouched():
    text = GOOD.replace("## Experience\ncontent", "## Experience\n```\n##summary\n```")
    assert user_profile.normalise_markdown(text) == text


def test_preamble_mentioning_summary_is_not_a_heading():
    text = "Here is the summary you asked for:\n\n" + GOOD
    assert user_profile.normalise_markdown(text) == GOOD
    assert user_profile.normalise_markdown("Summary: done\n##summary\nx").startswith("## Summary\nx")


def test_unclosed_wrapper_fence_after_preamble_is_dropped():
    assert user_profile.normalise_markdown("Here you go:\n```markdown\n" + GOOD + "\n```") == GOOD


def test_balanced_code_fence_at_the_end_is_kept():
    text = GOOD + "\n```\ncode\n```"
    assert user_profile.normalise_markdown(text) == text


def test_profile_deleted_during_generation_discards_the_result(client, llm):
    put_text(client, "notes")
    llm.on_call = lambda: client.post("/api/admin/delete-profile")
    r = client.post("/api/me/profile/generate")
    assert r.status_code == 409 and r.json()["code"] == "profile_missing"
    assert client.get("/api/me/profile").json()["profile_markdown"] is None
