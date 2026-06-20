# Maintenance Guide

## Dependency Management

### Automated Security Updates (Dependabot)

Dependabot is configured to automatically check for outdated and vulnerable dependencies:

**Configuration:** `.github/dependabot.yml`

- **Schedule:** Runs weekly on Mondays at 03:00 UTC
- **Pull Requests:** Groups development dependencies (minor/patch updates) to reduce PR spam
- **Review:** PRs are labeled with `dependencies` and `python` for easy filtering

#### Responding to Dependabot PRs

1. **Security vulnerabilities** (marked with ⚠️):
   - Review the CVE details
   - Run tests: `pytest tests/ --cov=lizenztool`
   - Merge immediately if tests pass

2. **Regular updates** (minor/patch versions):
   - Check the changelog for breaking changes
   - Run tests locally
   - Consider batching related updates into a single merge

3. **Major version updates**:
   - Created separately (not grouped)
   - May require code changes
   - Review the migration guide before merging

#### Manual Dependency Checks

```bash
# See outdated packages
pip list --outdated

# Check for security vulnerabilities
pip install safety
safety check

# Update to latest compatible versions
pip install --upgrade pip setuptools wheel
pip install -e ".[dev]" --upgrade
```

---

## Release Process

When preparing a release:

1. Update version in `pyproject.toml`
2. Run full test suite: `pytest tests/ -v --cov=lizenztool`
3. Create a commit and tag: `git tag v1.2.3`
4. Push: `git push origin main --tags`

---

## Monitoring

- **Security alerts:** Watch GitHub's Security tab for any disclosed vulnerabilities
- **Test coverage:** Aim to maintain ≥90% API coverage
- **Python version support:** Test against Python 3.11+ before releases

