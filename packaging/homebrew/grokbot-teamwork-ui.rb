# Homebrew formula for Bot Office. To publish it, put this file in a tap repository
# (github.com/Olivia295/homebrew-tap → Formula/grokbot-teamwork-ui.rb), then:
#   brew install Olivia295/tap/grokbot-teamwork-ui
#   brew services start grokbot-teamwork-ui      # keep it running, start at login
# On each release, point `url` at the new tag and update `sha256`
# (curl -L <url> | shasum -a 256).
class GrokbotTeamworkUi < Formula
  include Language::Python::Virtualenv

  desc "Watch your Grok Bot team or any multi-agent system hand off work in a living office"
  homepage "https://github.com/Olivia295/grokbot-teamwork-UI"
  url "https://github.com/Olivia295/grokbot-teamwork-UI/archive/refs/tags/v0.4.0.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"
  head "https://github.com/Olivia295/grokbot-teamwork-UI.git", branch: "main"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  service do
    run [opt_bin/"bot-office"]
    keep_alive true
    log_path var/"log/bot-office.log"
    error_log_path var/"log/bot-office.log"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/bot-office --version")
    port = free_port
    pid = spawn bin/"bot-office", "--demo", "--port", port.to_s
    sleep 3
    assert_match "\"ok\": true", shell_output("curl -s http://127.0.0.1:#{port}/health")
  ensure
    Process.kill("TERM", pid) if pid
  end
end
