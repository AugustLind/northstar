# Contributing

Start with the [development guide](docs/DEVELOPMENT.md) for module ownership and
checks. The application runs with Python 3.10+ and no third-party Python packages.
Node is needed for JavaScript checks; Chrome is needed for the browser workflow.

## Make a change

1. Describe the user-visible problem and expected result. For calculation changes,
   include a small example with independently calculated expected values.
2. Edit HTML in `web/templates/`, not generated `static/index.html`. Keep shell
   placeholders on standalone lines. Run `python3 scripts/build-ui.py` after UI edits.
3. Run the development guide's checks. Run `python3 scripts/smoke-browser.py` for
   changes to user flows. Use synthetic inputs; do not exercise a real portfolio.
4. Review the diff for private records and credentials. Open a pull request with
   the resulting behavior, checks run, and any remaining limitations.

A push to `main` triggers production deployment. Use a branch for review.
Do not include databases, portfolio exports, access keys, email credentials or
private server logs in issues, pull requests or commits.

## Documentation and issues

Keep first-use guidance and README steps consistent with the actual UI. Record
methodology changes and limitations in the technical reference. For bugs, include
reproduction steps and redacted error messages; provider failures need dates and
coverage context, never private holdings or credentials.

No project license has been selected yet. Do not assume the public repository
grants reuse rights. A license choice requires the repository owner's decision.
