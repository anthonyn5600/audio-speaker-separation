# Contributing to Audio Speaker Separation App

We love your input! We want to make contributing to this project as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features
- Becoming a maintainer

## Development Process

We use GitHub to host code, to track issues and feature requests, as well as accept pull requests.

## Pull Requests

Pull requests are the best way to propose changes to the codebase. We actively welcome your pull requests:

1. Fork the repo and create your branch from `main`.
2. If you've added code that should be tested, add tests.
3. If you've changed APIs, update the documentation.
4. Ensure the test suite passes.
5. Make sure your code lints.
6. Issue that pull request!

## Any contributions you make will be under the MIT Software License

In short, when you submit code changes, your submissions are understood to be under the same [MIT License](LICENSE) that covers the project.

## Report bugs using GitHub's [issue tracker](https://github.com/yourusername/audio-speaker-separation/issues)

We use GitHub issues to track public bugs. Report a bug by [opening a new issue](https://github.com/yourusername/audio-speaker-separation/issues/new).

## Write bug reports with detail, background, and sample code

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

## Development Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/yourusername/audio-speaker-separation.git
   cd audio-speaker-separation
   ```

3. Set up virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or
   venv\Scripts\activate  # Windows
   ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Run tests:
   ```bash
   cd audio_separator
   python manage.py test
   ```

## Code Style

We use the following tools to maintain code quality:

- **Black** for code formatting
- **Flake8** for linting
- **Django's** built-in testing framework

Run these before submitting:

```bash
# Format code
black .

# Check linting
flake8 .

# Run tests
python manage.py test
```

## Adding New Features

### Adding Audio Format Support

1. Update `ALLOWED_AUDIO_FORMATS` in `settings.py`
2. Add magic number validation in `forms.py`
3. Test with sample files

### Extending Security

1. Add new middleware to `middleware.py`
2. Update security tests
3. Document security implications

### UI Improvements

1. Modify templates in `processor/templates/`
2. Update CSS/JavaScript as needed
3. Ensure mobile responsiveness

## Testing

We maintain high test coverage. When adding features:

1. Write unit tests for new functions
2. Add integration tests for API endpoints
3. Test security features thoroughly
4. Include performance tests for processing pipeline

## Documentation

- Update README.md for user-facing changes
- Update PROJECT_DOCUMENTATION.md for technical details
- Add docstrings to new functions
- Update configuration documentation

## Security

For security issues, please:

1. **DO NOT** open a public issue
2. Email security@yourdomain.com
3. Include detailed reproduction steps
4. We'll respond within 48 hours

## License

By contributing, you agree that your contributions will be licensed under its MIT License.

## Questions?

Feel free to contact us if you have any questions about contributing!
