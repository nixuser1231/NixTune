# Development / try-it shell:  nix-shell   then   python -m nixtune
{ pkgs ? import <nixpkgs> { } }:

let
  py = pkgs.python3.withPackages (ps: [ ps.pyside6 ps.pytest ]);
in
pkgs.mkShell {
  packages = [ py pkgs.qt6.qtwayland pkgs.desktop-file-utils pkgs.polkit ];
  shellHook = ''
    export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
    export QT_PLUGIN_PATH="${pkgs.qt6.qtwayland}/${pkgs.qt6.qtbase.qtPluginPrefix}''${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"
    echo "NIXTUNE dev shell: run 'python -m nixtune' (or ./nixtune-check-deps)"
  '';
}
