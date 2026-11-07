"""What scoring records on a key Anthropic stopped accepting.

``rejected``: the key no longer signs in. ``not-permitted``: it can no longer
use the model this app runs. ``no-credit``: its account has run out of credit.
Saving a key clears the failure.
"""

from typing import Literal

KeyFailure = Literal["rejected", "not-permitted", "no-credit"]
