"""Review mechanics for review-ticket (skeleton for the failing-first run)."""
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("pin", "check", "post", "follow-up"))
    parser.parse_known_args()


if __name__ == "__main__":
    main()
