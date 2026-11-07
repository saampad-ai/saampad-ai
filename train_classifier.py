"""
train_classifier.py
--------------------
Run this once (and again after adding questions) to train and publish the
self-trained topic classifier using the Neon question bank.

Usage:
    python train_classifier.py
"""

import os
import sys
from dotenv import load_dotenv

SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from backend.pyq_engine import load_pyq_db
from backend.classifier import train_topic_classifier
from backend.storage import initialize_storage

if __name__ == "__main__":
    initialize_storage()
    df = load_pyq_db()
    print(f"Training on {len(df)} questions across {df['topic'].nunique()} topics...")

    result = train_topic_classifier(df)

    print(f"\nTrain size: {result['train_size']}  |  Test size: {result['test_size']}")
    print(f"Test accuracy: {result['accuracy']:.2%}")
    print("\nClassification report:")
    print(result["report"])
    print("\nModel saved to Neon Object Storage: models/topic_classifier.joblib")
    print("\nNOTE: Accuracy here is limited by how many examples exist PER TOPIC,")
    print("not just the total row count -- with 12+ topic classes, many still have")
    print("only 1-3 training examples each. This is EXPECTED and genuinely worth")
    print("showing live: more real PYQs per topic (especially for the thin classes)")
    print("will visibly raise accuracy on retraining -- a concrete, honest")
    print("demonstration of how training data size affects a model.")
