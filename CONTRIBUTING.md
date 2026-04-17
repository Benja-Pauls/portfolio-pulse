# Contributing to Portfolio Pulse

Thank you for your interest in contributing! This guide will help you get started.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/portfolio-pulse.git
   cd portfolio-pulse
   ```
3. **Create a branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```
4. **Set up the development environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Project Structure

Portfolio Pulse has two components:

- **This repo** (`portfolio-pulse/`) — the magazine generator and Vercel deployment
- **CLI toolkit** (`Stock_Portfolio/`) — 60+ commands for portfolio analysis

If your change touches the CLI toolkit, make sure to note that clearly in your PR.

## What to Work On

Check the [Issues](https://github.com/Benja-Pauls/portfolio-pulse/issues) page for open tasks. Here are areas where contributions are especially welcome:

### High Impact
- **Brokerage support** — TD Ameritrade, Fidelity, Interactive Brokers, Robinhood
- **Cross-platform notifications** — Linux/Windows support (currently macOS-only for iMessage)
- **Additional data sources** — options flow, dark pool data, alternative data
- **Test coverage** — unit tests for CLI commands and magazine generation

### Medium Impact
- **Magazine themes** — additional HTML/CSS templates for different styles
- **ML models** — additional prediction models beyond GradientBoosting
- **Visualization** — improved ASCII charts, new dashboard layouts
- **Documentation** — tutorials, video walkthroughs, wiki pages

### Good First Issues
- Typo fixes and documentation improvements
- Adding new tickers to the bottoming signal scanner
- Adding new macro indicators to the recession dashboard
- Improving error messages and edge case handling

## Code Style

- **Python**: Follow PEP 8. Use type hints where practical.
- **JavaScript**: Standard ES6+ for Vercel serverless functions.
- **HTML/CSS**: The magazine uses inline styles for self-contained output. Keep it that way.
- **Commits**: Write clear, descriptive commit messages. One logical change per commit.

## Pull Request Process

1. **Test your changes** — make sure existing commands still work
2. **Update documentation** if your change affects command usage or setup
3. **Keep PRs focused** — one feature or fix per PR
4. **Describe what and why** in the PR description, not just what you changed
5. **Link related issues** if applicable

### PR Title Format

Use a clear, concise title:
- `Add Fidelity brokerage support`
- `Fix RSI calculation for thin-volume stocks`
- `Add Linux notification support via notify-send`

## Sensitive Data

**Never commit:**
- API keys or secrets (`.env` files)
- OAuth tokens (`token.json`)
- Generated HTML issues (`issues/*.html`)
- Personal portfolio data

The `.gitignore` is configured to exclude these, but always double-check before committing.

## Reporting Issues

When reporting a bug, please include:
- Your OS and Python version
- The exact command you ran
- The full error output
- Whether you have the relevant API keys configured

## Questions?

Open a [Discussion](https://github.com/Benja-Pauls/portfolio-pulse/discussions) or file an issue. We are happy to help.

---

Thank you for helping make portfolio analysis accessible to self-directed investors!
