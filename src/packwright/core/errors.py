class PackwrightError(Exception):
    """Base exception for Packwright failures."""


class PackwrightValidationError(PackwrightError):
    """Raised when a Packwright document fails structural validation."""

    def __init__(self, issues):
        self.issues = list(issues)
        message = "Packwright validation failed"
        if self.issues:
            message += ":\n" + "\n".join("- " + issue for issue in self.issues)
        super().__init__(message)
