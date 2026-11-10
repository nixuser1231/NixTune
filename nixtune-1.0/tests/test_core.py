import importlib.machinery
import importlib.util
import os
import stat

import pytest

from nixtune.core import desktop, docs, gc, generations, privileged

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = "/nix/store/" + "a" * 32 + "-"


def load_helper():
    path = os.path.join(ROOT, "helper", "nixtune-helper")
    loader = importlib.machinery.SourceFileLoader("nt_helper", path)
    spec = importlib.util.spec_from_loader("nt_helper", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_helper_allowlist_is_minimal_and_never_deletes_generations():
    h = load_helper()
    assert set(h.ACTIONS) == {"gc", "optimise"}
    for tool, args in h.ACTIONS.values():
        assert tool == "nix-store"
        assert not any("generation" in a for a in args)
    assert h.main(["h"]) == 2
    assert h.main(["h", "rm"]) == 2
    assert h.main(["h", "gc", "extra"]) == 2
    assert h.main(["h", "--self-test"]) == 0


def test_helper_requires_root():
    h = load_helper()
    if os.geteuid() != 0:
        assert h.main(["h", "gc"]) == 77


def test_privileged_actions_match_helper():
    h = load_helper()
    assert set(privileged.ACTIONS) == set(h.ACTIONS)
    with pytest.raises(ValueError):
        privileged.plan("rm-rf")


def test_untrusted_user_writable_helper_refused(tmp_path):
    f = tmp_path / "helper"
    f.write_text("#!/bin/sh\n")
    f.chmod(0o755)
    ok, reason = privileged.is_trusted_path(str(f))
    if os.geteuid() != 0:
        assert not ok and "root" in reason
    f.chmod(0o777)
    assert not privileged.is_trusted_path(str(f))[0]


def test_gc_parsers():
    good = H + "abc-1.0"
    assert gc.parse_dead_paths(f"{good}\n{good}\nnot a path\n/etc/passwd\n") == [good]
    assert gc.parse_sizes("10\n20\n", 2) == [10, 20]
    assert gc.parse_sizes("10\nx\n", 2) is None
    assert gc.parse_sizes("10\n", 2) is None
    r = gc.parse_roots(
        "/nix/var/nix/profiles/system-1-link -> /nix/store/x\n"
        "/run/current-system -> /nix/store/y\n"
        "{memory} -> /nix/store/z\n"
        f"/home/u/result -> {good}\n")
    assert (r.total, r.profiles, r.system, r.running, r.other) == (4, 1, 1, 1, 1)
    assert r.result_links == [("/home/u/result", good)]


def test_generations_listing_and_commands(tmp_path):
    for n in (1, 2, 10):
        os.symlink(f"/nix/store/{n}", tmp_path / f"system-{n}-link")
    os.symlink("system-10-link", tmp_path / "system")
    (tmp_path / "system-x-link").write_text("")
    ref = generations.ProfileRef("t", str(tmp_path), "system", True)
    gens = generations.list_generations(ref)
    assert [g.number for g in gens] == [10, 2, 1]
    assert gens[0].is_default and not gens[1].is_default
    assert gens[0].created.year >= 2020
    cmd = generations.delete_command(ref, [2, 1, 1])
    assert cmd.startswith("sudo nix-env -p ") and cmd.endswith("--delete-generations 1 2")
    assert generations.keep_last_command(3, ref).endswith("+3")
    assert generations.older_than_command(30, ref) == "sudo nix-collect-garbage --delete-older-than 30d"
    with pytest.raises(ValueError):
        generations.delete_command(ref, [])
    with pytest.raises(ValueError):
        generations.keep_last_command(0, ref)
    assert generations.list_generations(generations.ProfileRef("x", "/nonexistent", "system", True)) == []


def test_generations_module_never_executes_anything():
    src = open(generations.__file__).read()
    assert "subprocess" not in src and "runner" not in src and "os.remove" not in src


def test_docs_url_allowlist():
    assert docs.is_allowed_doc_url("https://nixos.org/manual/nixos/stable/")
    assert docs.is_allowed_doc_url("https://search.nixos.org/options")
    assert not docs.is_allowed_doc_url("http://nixos.org/")
    assert not docs.is_allowed_doc_url("https://nixos.org.evil.com/")
    assert not docs.is_allowed_doc_url("file:///etc/passwd")
    assert not docs.is_allowed_doc_url("javascript:alert(1)")
    assert all(docs.is_allowed_doc_url(d.url) for d in docs.DOC_LINKS)
    assert docs.DOC_LINKS[0].url == "https://nixos.org/manual/nixos/stable/"


def test_desktop_entry(tmp_path, monkeypatch):
    assert desktop.quote_exec_arg("plain") == "plain"
    assert desktop.quote_exec_arg("a b") == '"a b"'
    assert desktop.quote_exec_arg("100%") == "100%%"
    text = desktop.desktop_entry_text(["/opt/my dir/nixtune-launch.sh"])
    assert desktop.validate_entry_text(text)
    assert 'Exec="/opt/my dir/nixtune-launch.sh"' in text
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    plan = desktop.plan_install()
    assert not desktop.is_installed()          # planning writes nothing
    assert not (tmp_path / "applications").exists()
    msgs = desktop.install(plan)
    assert desktop.is_installed() and msgs
    assert (tmp_path / "icons/hicolor/scalable/apps/nixtune.svg").is_file()
    desktop.uninstall()
    assert not desktop.is_installed()


def test_packaged_desktop_file_and_policy():
    text = open(os.path.join(ROOT, "packaging/nixtune.desktop")).read()
    assert desktop.validate_entry_text(text)
    pol = open(os.path.join(ROOT, "packaging/org.nixtune.helper.policy.in")).read()
    assert "@helper@" in pol and "auth_admin" in pol and "allow_active>yes" not in pol
    import xml.dom.minidom as md
    md.parseString(pol.replace("@helper@", "/nix/store/x/helper").split("?>", 1)[1].split("<policyconfig>", 1)[0] + "<policyconfig/>")


def test_launcher_scripts_are_executable():
    for name in ("nixtune-launch.sh", "nixtune-check-deps", "helper/nixtune-helper"):
        assert os.stat(os.path.join(ROOT, name)).st_mode & stat.S_IXUSR


def test_refuses_root(monkeypatch):
    from nixtune import app
    monkeypatch.setattr(app, "refuse_root", lambda: True)
    assert app.main([]) == app.EXIT_ROOT


def test_cli_check_deps_runs(capsys):
    from nixtune import cli
    rc = cli.check_deps_main([])
    out = capsys.readouterr().out
    assert "dependency check" in out and rc in (0, 1)
