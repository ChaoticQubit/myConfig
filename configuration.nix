{ ... }:

{
  nix.enable = false;

  nixpkgs.config.allowUnfree = true;
  nixpkgs.hostPlatform = "aarch64-darwin";

  system.primaryUser = "chaoticqubit";
  users.users.chaoticqubit = {
    home = "/Users/chaoticqubit";
  };
  system.stateVersion = 6;
  system.defaults = {
    NSGlobalDomain = {
      AppleInterfaceStyle = "Dark";
      KeyRepeat = 2;
      InitialKeyRepeat = 15;
      _HIHideMenuBar = false;
      AppleShowAllExtensions = true;
    };
    dock.autohide = false;
    finder.FXPreferredViewStyle = "Nlsv";
    trackpad.Clicking = true;
  };

  nix-homebrew = {
    enable = true;
    autoMigrate = true;
    user = "chaoticqubit";
  };
  homebrew = {
    enable = true;
    onActivation.cleanup = "zap"; # remove everything not listed here
    onActivation.autoUpdate = true;
    onActivation.upgrade = true;
    onActivation.extraFlags = [ "--force" ];
    casks = [
      "wezterm"
    ];

    brews = [
      "yt-dlp"
      "whisper-cpp"
      "htop"
      "tmux"
      "gh"
      "sqlite"
      "ggml"
      "bun"
      "codeburn"
    ];
  };
}
