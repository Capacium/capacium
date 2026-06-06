{
  description = "Capacium — Capability Packaging System for AI agents";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        packages.default = pkgs.python3Packages.buildPythonApplication {
          pname = "capacium";
          version = "0.14.0";
          format = "pyproject";
          src = self;
          propagatedBuildInputs = [ ];  # stdlib-only
          meta = with pkgs.lib; {
            description = "Capability Packaging System for AI agent capabilities";
            homepage = "https://capacium.xyz";
            license = licenses.asl20;
            mainProgram = "cap";
          };
        };

        apps.default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/cap";
        };
      });
}
