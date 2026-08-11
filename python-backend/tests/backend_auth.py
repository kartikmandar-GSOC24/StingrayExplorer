"""Shared launch credential for tests that exercise the fully secured app."""

TEST_BACKEND_SESSION_SECRET = "test-backend-session-" + "a" * 64
TEST_BACKEND_AUTH_HEADERS = {
    "X-Stingray-Session": TEST_BACKEND_SESSION_SECRET,
}
