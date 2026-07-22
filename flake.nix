{
  description = "ChaoticQubit's Dotfiles";

  inputs = {
    # Use `github:NixOS/nixpkgs/nixpkgs-26.05-darwin` to use Nixpkgs 26.05.
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-26.05-darwin";
    # Use `github:nix-darwin/nix-darwin/nix-darwin-26.05` to use Nixpkgs 26.05.
    nix-darwin.url = "github:nix-darwin/nix-darwin/nix-darwin-26.05";
    nix-darwin.inputs.nixpkgs.follows = "nixpkgs";

    home-manager.url = "github:nix-community/home-manager/release-26.05";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";

    nix-homebrew.url = "github:zhaofengli/nix-homebrew";
  };

  outputs = inputs@{ self, nix-darwin, nixpkgs, home-manager, nix-homebrew }: {
    darwinConfigurations."myMac" = nix-darwin.lib.darwinSystem {
      modules = [ 
        ./configuration.nix

	home-manager.darwinModules.home-manager
	{
	  home-manager.useGlobalPkgs = true;
	  home-manager.useUserPackages = true;
	  home-manager.users.chaoticqubit = import ./home.nix;
	}

	nix-homebrew.darwinModules.nix-homebrew
	{
          nix-homebrew = {
            enable = true;
            user = "chaoticqubit"; # Your system user account
            autoMigrate = true;     # Migrates old files safely
          };
        }
      ];
    };
  };
}
