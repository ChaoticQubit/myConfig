{ config, pkgs, ... }:

let
  dotfiles = "${config.home.homeDirectory}/.dotfiles";
  managedState = "${config.home.homeDirectory}/.local/state/home-manager-managed";
  npmGlobals = [
    "ccstatusline"
    "gh-axi"
    "tasks-axi"
    "chrome-devtools-axi"
    "lavish-axi"
    "quota-axi"
    "deepsec"
  ];
  imperativeTools = [
    "ccwarriors"
  ];
  uvTools = [
    "graphifyy"
  ];
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
    hmPath="$PATH"
    export PATH="$PATH:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    declared="${builtins.concatStringsSep " " npmGlobals}"
    manifest="${managedState}/npm-globals"
    run mkdir -p "${managedState}"
    if [ -f "$manifest" ]; then
      while read -r pkg; do
        if [ -z "$pkg" ]; then
          continue
        fi
        case " $declared " in
          *" $pkg "*) ;;
          *) run npm uninstall -g "$pkg" ;;
        esac
      done < "$manifest"
    fi
    if [ -n "$declared" ]; then
      run npm install -g $declared
    fi
    printf '%s\n' $declared > "$manifest"
    export PATH="$hmPath"
  '';

  home.activation.uvTools = config.lib.dag.entryAfter [ "writeBoundary" ] ''
    hmPath="$PATH"
    export PATH="$PATH:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"
    declared="${builtins.concatStringsSep " " uvTools}"
    manifest="${managedState}/uv-tools"
    run mkdir -p "${managedState}"
    if [ -f "$manifest" ]; then
      while read -r pkg; do
        if [ -z "$pkg" ]; then
          continue
        fi
        case " $declared " in
          *" $pkg "*) ;;
          *) run uv tool uninstall "$pkg" ;;
        esac
      done < "$manifest"
    fi
    for pkg in $declared; do
      run uv tool install "$pkg"
    done
    printf '%s\n' $declared > "$manifest"
    export PATH="$hmPath"
  '';

  home.activation.imperativeTools = config.lib.dag.entryAfter [ "writeBoundary" ] ''
    hmPath="$PATH"
    export PATH="$PATH:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

    install_ccwarriors() {
      if [ ! -x "$HOME/.ccwarriors/bin/ccwarriors" ]; then
        curl -fsSL https://ccwarriors.xyz/install.sh | CCWARRIORS_NO_RUN=1 CCWARRIORS_REF=badge bash
        if [ ! -x "$HOME/.ccwarriors/bin/ccwarriors" ]; then
          echo "error: the ccwarriors installer finished but left no executable at ~/.ccwarriors/bin/ccwarriors" >&2
          return 1
        fi
      fi
      if [ ! -f "$HOME/.claude-warriors/config.json" ]; then
        echo "ccwarriors is installed but not logged in; run 'ccwarriors' once, then rebuild to start background sync"
        return 0
      fi
      "$HOME/.ccwarriors/bin/ccwarriors" autosync on
    }

    uninstall_ccwarriors() {
      launchctl bootout "gui/$(id -u)/xyz.ccwarriors.sync" 2>/dev/null || true
      pkill -f '\.ccwarriors/cli\.js' 2>/dev/null || true
      rm -f "$HOME/Library/LaunchAgents/xyz.ccwarriors.sync.plist"
      rm -f "$HOME/.local/bin/ccwarriors"
      rm -rf "$HOME/.ccwarriors" "$HOME/.claude-warriors"
    }

    declared="${builtins.concatStringsSep " " imperativeTools}"
    manifest="${managedState}/imperative-tools"
    run mkdir -p "${managedState}"
    if [ -f "$manifest" ]; then
      while read -r tool; do
        if [ -z "$tool" ]; then
          continue
        fi
        case " $declared " in
          *" $tool "*) ;;
          *)
            if ! command -v "uninstall_$tool" >/dev/null 2>&1; then
              echo "error: $tool was dropped from imperativeTools but its uninstall_$tool recipe is gone too, so it cannot be removed" >&2
              echo "       restore the recipe in home.nix, rebuild once to uninstall it, then delete the recipe" >&2
              exit 1
            fi
            run "uninstall_$tool"
            ;;
        esac
      done < "$manifest"
    fi
    for tool in $declared; do
      if ! command -v "install_$tool" >/dev/null 2>&1; then
        echo "error: imperativeTools lists $tool but home.nix defines no install_$tool recipe" >&2
        exit 1
      fi
      run "install_$tool"
    done
    printf '%s\n' $declared > "$manifest"
    export PATH="$hmPath"
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
