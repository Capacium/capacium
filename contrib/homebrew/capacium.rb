class Capacium < Formula
  desc "Capability Packaging System for AI agent capabilities"
  homepage "https://github.com/typelicious/capacium"
  url "https://github.com/typelicious/capacium/archive/refs/tags/v0.4.0.tar.gz"
  license "Apache-2.0"

  depends_on "python@3.12"

  def install
    system "python3", "-m", "pip", "install", *std_pip_install_args(buildpath: ".")
  end

  test do
    system "#{bin}/cap", "--version"
  end
end
