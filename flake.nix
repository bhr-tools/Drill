{
  description = "Drill — rapid-fire coding exercises, solved in your own editor";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      # Compilers the exercises are built with, available to drill at runtime. Nix
      # exercises use the system's nix, and this flake's nixpkgs as their nixpkgs.
      toolchain = pkgs: with pkgs; [ gcc jdk ocaml ];
    in {
      packages = forAllSystems (pkgs: rec {
        drill = pkgs.python3Packages.buildPythonApplication {
          pname = "drill";
          version = "0.1.0";
          pyproject = true;
          src = ./.;

          build-system = [ pkgs.python3Packages.setuptools ];
          nativeBuildInputs = [ pkgs.installShellFiles ];

          # The scripts ask `drill __complete` for the candidates, so they never go stale
          postInstall = ''
            export PYTHONPATH="$out/${pkgs.python3.sitePackages}''${PYTHONPATH:+:$PYTHONPATH}"
            ${pkgs.python3.interpreter} -m drill completion zsh > _drill
            ${pkgs.python3.interpreter} -m drill completion bash > drill.bash
            installShellCompletion --cmd drill --zsh _drill --bash drill.bash
          '';

          makeWrapperArgs = [
            "--prefix" "PATH" ":" (pkgs.lib.makeBinPath (toolchain pkgs))
            "--set-default" "DRILL_NIXPKGS" "${nixpkgs}"
          ];

          meta = with pkgs.lib; {
            description = "Rapid-fire coding exercises, solved in your own editor";
            license = licenses.mit;
            mainProgram = "drill";
          };
        };
        default = drill;
      });

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.python3
            pkgs.ruff
            # Runs the working tree, so edits to src/ apply immediately. No bytecode
            # cache: it would change the tree that a path: flake input hashes.
            (pkgs.writeShellScriptBin "drill" ''
              PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$DRILL_ROOT/src''${PYTHONPATH:+:$PYTHONPATH}" \
                exec python3 -m drill "$@"
            '')
          ] ++ toolchain pkgs;
          shellHook = ''
            export DRILL_ROOT="$PWD"
            export DRILL_NIXPKGS="${nixpkgs}"
          '';
        };
      });
    };
}
