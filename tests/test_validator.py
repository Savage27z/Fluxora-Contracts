"""
tests/test_validator.py

Test suite for script/validate-doc-alignment.py.
Uses pytest and unittest.mock to simulate file-system states.
Targets 95%+ code coverage of the validator module.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Load the module under test without executing __main__
# ---------------------------------------------------------------------------

_SCRIPT = Path(__file__).resolve().parent.parent / "script" / "validate-doc-alignment.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_doc_alignment", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vda = _load_module()

# ---------------------------------------------------------------------------
# Shared fixtures: minimal Rust source stubs and doc stubs
# ---------------------------------------------------------------------------

MINIMAL_LIB_RS = """\
#[contractimpl]
impl MyContract {
    pub fn init(env: Env) -> Result<(), Error> { Ok(()) }
    pub fn create_stream(env: Env) -> Result<u64, Error> { Ok(0) }
    pub fn withdraw(env: Env) -> Result<i128, Error> { Ok(0) }
}
// allowlisted helper — must NOT be required in docs
pub fn save_stream(env: &Env) {}
fn private_helper() {}
"""

MINIMAL_EVENTS_RS = """\
pub fn emit_created(env: &Env, id: u64) {
    env.events().publish(
        (Symbol::short(&env, "created"), id),
        payload,
    );
}
pub fn emit_withdrew(env: &Env, id: u64) {
    env.events().publish(
        (Symbol::new(&env, "withdrew"), id),
        payload,
    );
}
"""

MINIMAL_ERROR_RS = """\
#[contracterror]
pub enum ContractError {
    StreamNotFound = 1,
    InvalidState = 2,
}
"""

STREAMING_DOC = "# Streaming\n`init`, `create_stream`, `withdraw` are entrypoints.\n"
EVENTS_DOC = "# Events\n`created` and `withdrew` are the event topics.\n"
ERROR_DOC = "# Errors\n`StreamNotFound` = 1, `InvalidState` = 2.\n"


def _write_files(
    tmp_path: Path,
    lib_rs: str = MINIMAL_LIB_RS,
    events_rs: str = MINIMAL_EVENTS_RS,
    error_rs: str = MINIMAL_ERROR_RS,
    streaming: str = STREAMING_DOC,
    events: str = EVENTS_DOC,
    error: str = ERROR_DOC,
):
    """Write all six files to tmp_path and return their paths."""
    contract = tmp_path / "lib.rs"
    ev_src = tmp_path / "events.rs"
    err_src = tmp_path / "error.rs"
    s_doc = tmp_path / "streaming.md"
    e_doc = tmp_path / "events.md"
    err_doc = tmp_path / "error.md"

    for path, content in [
        (contract, lib_rs),
        (ev_src, events_rs),
        (err_src, error_rs),
        (s_doc, streaming),
        (e_doc, events),
        (err_doc, error),
    ]:
        path.write_text(content, encoding="utf-8")

    return contract, ev_src, err_src, s_doc, e_doc, err_doc


# ---------------------------------------------------------------------------
# extract_entrypoints
# ---------------------------------------------------------------------------

class TestExtractEntrypoints:
    def test_finds_pub_fn(self):
        assert "init" in vda.extract_entrypoints("pub fn init(env: Env) {}")

    def test_ignores_private_fn(self):
        assert "helper" not in vda.extract_entrypoints("fn helper() {}")

    def test_allowlist_excluded(self):
        assert "save_stream" not in vda.extract_entrypoints(
            "pub fn save_stream(env: &Env) {}"
        )

    def test_multiple_entrypoints(self):
        src = "pub fn alpha() {}\npub fn beta() {}"
        result = vda.extract_entrypoints(src)
        assert {"alpha", "beta"}.issubset(result)

    def test_indented_pub_fn(self):
        assert "indented" in vda.extract_entrypoints("    pub fn indented(env: Env) {}")

    def test_generic_pub_fn(self):
        # pub fn foo<T>( should also match
        assert "generic_fn" in vda.extract_entrypoints("pub fn generic_fn<T>(x: T) {}")

    def test_empty_source(self):
        assert vda.extract_entrypoints("") == set()

    def test_returns_set_type(self):
        assert isinstance(vda.extract_entrypoints("pub fn foo() {}"), set)


# ---------------------------------------------------------------------------
# extract_event_symbols
# ---------------------------------------------------------------------------

class TestExtractEventSymbols:
    def test_finds_symbol_short(self):
        src = 'Symbol::short(&env, "created")'
        assert "created" in vda.extract_event_symbols(src)

    def test_finds_symbol_new(self):
        src = 'Symbol::new(&env, "withdrew")'
        assert "withdrew" in vda.extract_event_symbols(src)

    def test_finds_both_variants(self):
        src = 'Symbol::short(&env, "paused") Symbol::new(&env, "resumed")'
        result = vda.extract_event_symbols(src)
        assert {"paused", "resumed"}.issubset(result)

    def test_deduplicates(self):
        src = 'Symbol::short(&env, "created") Symbol::short(&env, "created")'
        assert len(vda.extract_event_symbols(src)) == 1

    def test_whitespace_tolerance(self):
        src = 'Symbol::short( &env , "spaced" )'
        assert "spaced" in vda.extract_event_symbols(src)

    def test_does_not_match_symbol_short_macro(self):
        # Old-style symbol_short!() should NOT match the new regex
        src = 'symbol_short!("old_style")'
        assert "old_style" not in vda.extract_event_symbols(src)

    def test_empty_source(self):
        assert vda.extract_event_symbols("") == set()

    def test_returns_set_type(self):
        assert isinstance(vda.extract_event_symbols('Symbol::short(&e, "x")'), set)


# ---------------------------------------------------------------------------
# extract_error_variants
# ---------------------------------------------------------------------------

class TestExtractErrorVariants:
    def test_finds_variants(self):
        src = "pub enum ContractError {\n    StreamNotFound = 1,\n    InvalidState = 2,\n}"
        result = vda.extract_error_variants(src)
        assert {"StreamNotFound", "InvalidState"} == result

    def test_ignores_lowercase_names(self):
        src = "    notAVariant = 1,\n    ValidVariant = 2,"
        result = vda.extract_error_variants(src)
        assert "ValidVariant" in result
        assert "notAVariant" not in result

    def test_no_variants(self):
        assert vda.extract_error_variants("no enum here") == set()

    def test_empty_source(self):
        assert vda.extract_error_variants("") == set()

    def test_returns_set_type(self):
        assert isinstance(vda.extract_error_variants("    Foo = 1,"), set)

    def test_multiple_variants(self):
        src = "    Alpha = 1,\n    Beta = 2,\n    Gamma = 3,"
        result = vda.extract_error_variants(src)
        assert result == {"Alpha", "Beta", "Gamma"}


# ---------------------------------------------------------------------------
# check_missing
# ---------------------------------------------------------------------------

class TestCheckMissing:
    def test_all_present(self):
        assert vda.check_missing({"foo", "bar"}, "foo bar baz") == set()

    def test_some_missing(self):
        assert vda.check_missing({"foo", "xyz_absent"}, "foo is here") == {"xyz_absent"}

    def test_all_missing(self):
        result = vda.check_missing({"xyz_foo", "xyz_bar"}, "nothing relevant")
        assert result == {"xyz_foo", "xyz_bar"}

    def test_empty_identifiers(self):
        assert vda.check_missing(set(), "anything") == set()

    def test_empty_doc(self):
        assert vda.check_missing({"foo"}, "") == {"foo"}

    def test_returns_set_type(self):
        assert isinstance(vda.check_missing({"a"}, "a"), set)


# ---------------------------------------------------------------------------
# validate() — integration-level tests
# ---------------------------------------------------------------------------

class TestValidate:
    def test_passes_on_full_alignment(self, tmp_path):
        paths = _write_files(tmp_path)
        assert vda.validate(*paths) == 0

    def test_fails_on_missing_entrypoint(self, tmp_path):
        streaming = "# Streaming\nOnly `init` is documented here.\n"
        paths = _write_files(tmp_path, streaming=streaming)
        assert vda.validate(*paths) == 1

    def test_fails_on_missing_event_symbol(self, tmp_path):
        events = "# Events\nOnly `created` is documented here.\n"
        paths = _write_files(tmp_path, events=events)
        assert vda.validate(*paths) == 1

    def test_fails_on_missing_error_variant(self, tmp_path):
        error = "# Errors\nOnly `StreamNotFound` is documented here.\n"
        paths = _write_files(tmp_path, error=error)
        assert vda.validate(*paths) == 1

    def test_fails_on_all_docs_drifted(self, tmp_path):
        paths = _write_files(
            tmp_path,
            streaming="# Streaming\nno entrypoints here\n",
            events="# Events\nno symbols here\n",
            error="# Errors\nno variants here\n",
        )
        assert vda.validate(*paths) == 1

    def test_allowlisted_entrypoint_not_required(self, tmp_path):
        # save_stream is in lib.rs but allowlisted; docs don't need it
        streaming = "# Streaming\n`init`, `create_stream`, `withdraw`\n"
        paths = _write_files(tmp_path, streaming=streaming)
        assert vda.validate(*paths) == 0

    def test_prints_ok_on_success(self, tmp_path, capsys):
        paths = _write_files(tmp_path)
        vda.validate(*paths)
        assert "OK:" in capsys.readouterr().out

    def test_prints_missing_doc_message(self, tmp_path, capsys):
        streaming = "# Streaming\nOnly `init` is documented here.\n"
        paths = _write_files(tmp_path, streaming=streaming)
        vda.validate(*paths)
        out = capsys.readouterr().out
        assert "MISSING DOC:" in out
        assert "streaming.md" in out

    def test_missing_entrypoint_message_contains_kind(self, tmp_path, capsys):
        streaming = "# Streaming\nOnly `init` is documented here.\n"
        paths = _write_files(tmp_path, streaming=streaming)
        vda.validate(*paths)
        assert "entrypoint" in capsys.readouterr().out

    def test_missing_event_message_contains_kind(self, tmp_path, capsys):
        events = "# Events\nOnly `created` is documented here.\n"
        paths = _write_files(tmp_path, events=events)
        vda.validate(*paths)
        assert "event symbol" in capsys.readouterr().out

    def test_missing_error_message_contains_kind(self, tmp_path, capsys):
        error = "# Errors\nOnly `StreamNotFound` is documented here.\n"
        paths = _write_files(tmp_path, error=error)
        vda.validate(*paths)
        assert "error variant" in capsys.readouterr().out

    def test_utf8_encoding_used(self, tmp_path):
        # Write files with non-ASCII content to confirm utf-8 reads succeed
        streaming = "# Streaming\n`init`, `create_stream`, `withdraw` — résumé\n"
        paths = _write_files(tmp_path, streaming=streaming)
        assert vda.validate(*paths) == 0

    def test_path_outside_repo_root_does_not_raise(self, tmp_path, capsys):
        # doc_path outside REPO_ROOT triggers the ValueError branch in display
        streaming = "# Streaming\nOnly `init` is documented here.\n"
        paths = _write_files(tmp_path, streaming=streaming)
        # tmp_path is outside REPO_ROOT on most systems; should not raise
        vda.validate(*paths)
        assert "MISSING DOC:" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main() — file-not-found guard and happy path
# ---------------------------------------------------------------------------

class TestMain:
    def _patch_paths(self, monkeypatch, tmp_path, missing=None):
        """Patch module-level path constants to point at tmp_path files."""
        contract, ev_src, err_src, s_doc, e_doc, err_doc = _write_files(tmp_path)
        paths = {
            "CONTRACT_SRC": contract,
            "EVENTS_SRC": ev_src,
            "ERROR_SRC": err_src,
            "DOC_STREAMING": s_doc,
            "DOC_EVENTS": e_doc,
            "DOC_ERROR": err_doc,
        }
        if missing:
            # Replace the named path with a non-existent one
            paths[missing] = tmp_path / "nonexistent_file.rs"
        for attr, val in paths.items():
            monkeypatch.setattr(vda, attr, val)

    def test_missing_contract_returns_1(self, tmp_path, monkeypatch):
        self._patch_paths(monkeypatch, tmp_path, missing="CONTRACT_SRC")
        assert vda.main() == 1

    def test_missing_events_src_returns_1(self, tmp_path, monkeypatch):
        self._patch_paths(monkeypatch, tmp_path, missing="EVENTS_SRC")
        assert vda.main() == 1

    def test_missing_error_src_returns_1(self, tmp_path, monkeypatch):
        self._patch_paths(monkeypatch, tmp_path, missing="ERROR_SRC")
        assert vda.main() == 1

    def test_missing_streaming_doc_returns_1(self, tmp_path, monkeypatch):
        self._patch_paths(monkeypatch, tmp_path, missing="DOC_STREAMING")
        assert vda.main() == 1

    def test_missing_events_doc_returns_1(self, tmp_path, monkeypatch):
        self._patch_paths(monkeypatch, tmp_path, missing="DOC_EVENTS")
        assert vda.main() == 1

    def test_missing_error_doc_returns_1(self, tmp_path, monkeypatch):
        self._patch_paths(monkeypatch, tmp_path, missing="DOC_ERROR")
        assert vda.main() == 1

    def test_all_files_aligned_returns_0(self, tmp_path, monkeypatch):
        self._patch_paths(monkeypatch, tmp_path)
        assert vda.main() == 0

    def test_missing_file_prints_error(self, tmp_path, monkeypatch, capsys):
        self._patch_paths(monkeypatch, tmp_path, missing="CONTRACT_SRC")
        vda.main()
        assert "ERROR:" in capsys.readouterr().out

    def test_drift_returns_1_via_main(self, tmp_path, monkeypatch):
        contract, ev_src, err_src, s_doc, e_doc, err_doc = _write_files(
            tmp_path,
            streaming="# Streaming\nOnly `init` is documented here.\n",
        )
        monkeypatch.setattr(vda, "CONTRACT_SRC", contract)
        monkeypatch.setattr(vda, "EVENTS_SRC", ev_src)
        monkeypatch.setattr(vda, "ERROR_SRC", err_src)
        monkeypatch.setattr(vda, "DOC_STREAMING", s_doc)
        monkeypatch.setattr(vda, "DOC_EVENTS", e_doc)
        monkeypatch.setattr(vda, "DOC_ERROR", err_doc)
        assert vda.main() == 1
