{
  description = "NIXTUNE - maintenance, diagnostics and tuning for NixOS";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
      mkPackage = pkgs: pkgs.python3Packages.buildPythonApplication {
        pname = "nixtune";
        version = "1.0.0";
        pyproject = true;
        src = ./.;
        build-system = [ pkgs.python3Packages.setuptools ];
        dependencies = [ pkgs.python3Packages.pyside6 ];
        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.desktop-file-utils ];
        buildInputs = [ pkgs.qt6.qtbase pkgs.qt6.qtwayland ];
        dontWrapQtApps = true;
        makeWrapperArgs = [ "\${qtWrapperArgs[@]}" ];
        # PySide6 wheels bring their own Qt; wrapping only adds the Wayland plugin path.
        postInstall = ''
          # privileged helper: root-owned, read-only, in the Nix store
          install -Dm755 helper/nixtune-helper $out/libexec/nixtune/nixtune-helper
          patchShebangs $out/libexec/nixtune/nixtune-helper
          # polkit policy bound to exactly that helper path
          mkdir -p $out/share/polkit-1/actions
          substitute packaging/org.nixtune.helper.policy.in \
            $out/share/polkit-1/actions/org.nixtune.helper.policy \
            --subst-var-by helper $out/libexec/nixtune/nixtune-helper
          install -Dm644 packaging/nixtune.desktop $out/share/applications/nixtune.desktop
          install -Dm644 src/nixtune/assets/nixtune.svg \
            $out/share/icons/hicolor/scalable/apps/nixtune.svg
          desktop-file-validate $out/share/applications/nixtune.desktop
        '';
        doCheck = false;
        meta = {
          description = "Maintenance, diagnostics and tuning for NixOS";
          mainProgram = "nixtune";
          platforms = nixpkgs.lib.platforms.linux;
        };
      };
    in
    {
      packages = forAll (pkgs: rec { nixtune = mkPackage pkgs; default = nixtune; });

      apps = forAll (pkgs: rec {
        nixtune = { type = "app"; program = "${self.packages.${pkgs.system}.nixtune}/bin/nixtune"; };
        default = nixtune;
      });

      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: [ ps.pyside6 ps.pytest ]))
            pkgs.qt6.qtwayland pkgs.desktop-file-utils
          ];
          shellHook = ''export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"'';
        };
      });

      # programs.nixtune.enable = true;
      nixosModules.default = { config, lib, pkgs, ... }: {
        options.programs.nixtune.enable = lib.mkEnableOption "NIXTUNE, a NixOS maintenance and tuning tool";
        config = lib.mkIf config.programs.nixtune.enable {
          environment.systemPackages = [ self.packages.${pkgs.system}.nixtune ];
          environment.pathsToLink = [ "/share/polkit-1" "/libexec/nixtune" ];
          security.polkit.enable = true;
        };
      };
    };
}
