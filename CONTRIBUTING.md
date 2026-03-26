# Contributing to PowerScale Exporter

Thank you for your interest in contributing to the PowerScale Prometheus Exporter! This document provides guidelines and information for contributors.

## 🚀 Getting Started

### Prerequisites

- Python 3.11 or higher
- Docker and Docker Compose
- Git
- Access to a Dell PowerScale/Isilon cluster (for testing)

### Development Setup

1. **Fork the Repository**
   ```bash
   # Fork on GitHub, then clone your fork
   git clone https://github.com/your-username/powerscale-exporter.git
   cd powerscale-exporter
   ```

2. **Set Up Development Environment**
   ```bash
   # Install development dependencies
   pip install -e ".[dev]"
   
   # Set up pre-commit hooks (optional but recommended)
   pre-commit install
   ```

3. **Verify Setup**
   ```bash
   # Run tests to ensure everything works
   pytest
   
   # Check code formatting
   black --check .
   ruff check .
   mypy exporter/
   ```

## 🏗️ Development Workflow

### 1. Create a Feature Branch

```bash
# Create and checkout a new branch
git checkout -b feature/your-feature-name

# Or for bug fixes
git checkout -b fix/issue-description
```

### 2. Make Your Changes

- Follow the existing code style and patterns
- Add type hints to new functions
- Write tests for new functionality
- Update documentation as needed

### 3. Run Quality Checks

```bash
# Format code
black .

# Check linting
ruff check .

# Type checking
mypy exporter/ --ignore-missing-imports

# Run tests
pytest

# Security scan
safety check
bandit -r exporter/
```

### 4. Commit Your Changes

```bash
# Stage changes
git add .

# Commit with descriptive message
git commit -m "feat: add new metric for cluster throughput"

# Use conventional commit messages:
# feat: new feature
# fix: bug fix
# docs: documentation changes
# style: formatting changes
# refactor: code refactoring
# test: adding or updating tests
# chore: maintenance tasks
```

### 5. Push and Create Pull Request

```bash
# Push to your fork
git push origin feature/your-feature-name

# Create pull request on GitHub
```

## 📝 Code Style Guidelines

### Python Code Style

We follow standard Python conventions:

- **PEP 8** compliance
- **Type hints** for all functions
- **Docstrings** for all public functions and classes
- **Maximum line length**: 88 characters (Black default)

### Example Code Style

```python
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class OneFSClient:
    """Client for interacting with OneFS API."""
    
    def __init__(self, host: str, port: int = 8080) -> None:
        """Initialize the OneFS client.
        
        Args:
            host: OneFS cluster hostname
            port: API port number
        """
        self.host = host
        self.port = port
    
    def get_cluster_health(self) -> Dict[str, Any]:
        """Get cluster health status.
        
        Returns:
            Dictionary containing cluster health information
            
        Raises:
            ConnectionError: If unable to connect to cluster
        """
        # Implementation here
        pass
```

### Naming Conventions

- **Variables and functions**: `snake_case`
- **Classes**: `PascalCase`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private methods**: `_leading_underscore`

## 🧪 Testing Guidelines

### Test Structure

```
test/
├── conftest.py              # Pytest configuration and fixtures
├── test_exporter.py         # Main application tests
├── test_scraper.py          # Scraper component tests
└── integration/             # Integration tests
    └── test_api.py          # API integration tests
```

### Writing Tests

1. **Unit Tests**: Test individual functions and classes
2. **Integration Tests**: Test component interactions
3. **End-to-End Tests**: Test complete workflows

### Example Test

```python
import pytest
from unittest.mock import Mock, patch
from exporter.scraper import OneFSClient

class TestOneFSClient:
    """Test cases for OneFS client."""
    
    def test_initialization(self):
        """Test client initialization."""
        client = OneFSClient("test-host", 8080)
        assert client.host == "test-host"
        assert client.port == 8080
    
    @patch('exporter.scraper.requests.Session')
    def test_authentication(self, mock_session):
        """Test API authentication."""
        mock_session.return_value = Mock()
        client = OneFSClient("test-host")
        # Test authentication logic
        assert client._authenticate() is not None
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=exporter --cov-report=html

# Run specific test file
pytest test/test_exporter.py

# Run with specific markers
pytest -m unit
pytest -m integration
```

## 📚 Documentation Guidelines

### Updating Documentation

1. **README.md**: Update for new features or configuration changes
2. **API Documentation**: Update docstrings for new functions
3. **CHANGELOG.md**: Add entries for significant changes

### Documentation Style

- Use clear, concise language
- Include code examples
- Provide configuration options
- Add troubleshooting information

## 🔧 Development Tools

### Pre-commit Setup

Install pre-commit hooks for automated quality checks:

```bash
pip install pre-commit
pre-commit install
```

### IDE Configuration

#### VS Code

Install these extensions:
- Python
- Black Formatter
- Ruff
- Docker

Configure in `.vscode/settings.json`:

```json
{
    "python.defaultInterpreterPath": "./.venv/bin/python",
    "python.formatting.provider": "black",
    "python.linting.enabled": true,
    "python.linting.ruffEnabled": true
}
```

## 🐛 Bug Reports

### Reporting Bugs

1. **Search existing issues** first
2. **Use the bug report template**
3. **Include environment information**:
   - Python version
   - PowerScale/Isilon version
   - Exporter version
   - Docker version (if applicable)

### Bug Report Template

```markdown
## Bug Description
Brief description of the bug

## Environment
- Python version:
- PowerScale/Isilon version:
- Exporter version:
- Docker version:

## Steps to Reproduce
1. Step one
2. Step two
3. Step three

## Expected Behavior
What should happen

## Actual Behavior
What actually happens

## Logs
Include relevant logs here
```

## 💡 Feature Requests

### Requesting Features

1. **Check existing issues** and discussions
2. **Use the feature request template**
3. **Describe the use case** clearly
4. **Consider implementation complexity**

### Feature Request Template

```markdown
## Feature Description
Clear description of the feature

## Use Case
Why is this feature needed?

## Proposed Solution
How should this feature work?

## Alternatives Considered
What other approaches did you consider?

## Additional Context
Any other relevant information
```

## 🔍 Code Review Process

### Review Guidelines

1. **Functionality**: Does the code work as intended?
2. **Style**: Does it follow project conventions?
3. **Tests**: Are there adequate tests?
4. **Documentation**: Is the documentation updated?
5. **Performance**: Are there performance implications?

### Review Checklist

- [ ] Code follows style guidelines
- [ ] Tests pass and provide good coverage
- [ ] Documentation is updated
- [ ] No security vulnerabilities
- [ ] Error handling is appropriate
- [ ] Logging is adequate
- [ ] Breaking changes are documented

## 🚀 Release Process

### Release Checklist

1. **All tests pass**
2. **Documentation is updated**
3. **CHANGELOG.md is updated**
4. **Version is bumped**
5. **Security scan passes**
6. **Manual testing completed**

### Version Bumping

We use semantic versioning:
- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

## 🤝 Community Guidelines

### Code of Conduct

- Be respectful and inclusive
- Welcome newcomers and help them learn
- Focus on constructive feedback
- Assume good intentions

### Getting Help

- **GitHub Issues**: For bug reports and feature requests
- **Discussions**: For general questions and ideas
- **Documentation**: Check existing docs first

## 📞 Contact

For questions about contributing:

- **GitHub Issues**: For specific issues and questions
- **Discussions**: For general questions and ideas
- **Maintainers**: Tag maintainers for urgent issues

---

Thank you for contributing to the PowerScale Exporter! Your contributions help make this project better for everyone. 🚀
