# hash_generator.py
from werkzeug.security import generate_password_hash
import sys

if len(sys.argv) != 2:
    print("Użycie: python hash_generator.py 'TwojeHaslo'")
    sys.exit(1)

password = sys.argv[1]
hashed_password = generate_password_hash(password)

print("\nOryginalne hasło:", password)
print("Zahashowane hasło (do wklejenia w .env):")
print(hashed_password)
print()
