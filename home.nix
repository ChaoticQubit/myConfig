{ config, pkgs, ... }:

let
  dotfiles = "${config.home.homeDirectory}/.dotfiles";
in

{
  home.username = "chaoticqubit";
  home.homeDirectory = "/Users/chaoticqubit";
  home.stateVersion = "24.11";
  home.packages = with pkgs; [
    ripgrep
    fd
    fzf
    jq
    lazygit
    neovim
    nerd-fonts.hack
  ];
  fonts.fontconfig.enable = true;
  home.sessionVariables.EDITOR = "nvim";

  home.activation.npmGlobals = config.lib.dag.entryAfter [ "writeBoundary" ] ''
    run /opt/homebrew/bin/npm install -g \
      gh-axi \
      tasks-axi \
      chrome-devtools-axi \
      lavish-axi \
      quota-axi
  '';

  programs.zsh = {
    enable = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;
      
    shellAliases = {
      ".." = "cd ..";
      add = "git add .";
      push = "git push";
      pull = "git pull";
      m = "git switch main";
      cc = "claude --dangerously-skip-permissions";
      co = "codex --full-auto";
    };
    initContent = ''
      bindkey '^f' autosuggest-accept

      commit() {
	git commit -m "$*"
      }
    '';
  };

  programs.git.settings.user = {
    name = "chaoticqubit";
    email = "chaoticqubit@gmail.com";
  };

  programs.starship = {
    enable = true;
    settings = {
      add_newline = false;
      format = "$directory$git_branch$git_status$cmd_duration$line_break$character";
      character = {
	success_symbol = "[❯](purple)";
	error_symbol = "[❯](red)";
      };
      cmd_duration.format = "[$duration]($style) ";
    };
  };

  xdg.configFile."nvim".source = ./nvim;
  xdg.configFile."wezterm".source = ./wezterm;
  xdg.configFile."herdr/config.toml".source = ./herdr/config.toml;
  home.file.".claude/settings.json" = {
    source = config.lib.file.mkOutOfStoreSymlink "${dotfiles}/claude/settings.json";
    force = true;
  };
  home.file.".claude/skills" = {
    source = config.lib.file.mkOutOfStoreSymlink "${dotfiles}/claude/skills";
    force = true;
  };
  home.file.".claude/hooks" = {
    source = config.lib.file.mkOutOfStoreSymlink "${dotfiles}/claude/hooks";
    force = true;
  };
  home.file.".claude/CLAUDE.md" = {
    source = config.lib.file.mkOutOfStoreSymlink "${dotfiles}/claude/CLAUDE.md";
    force = true;
  };
}
