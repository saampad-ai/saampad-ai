"""
classifier.py
-------------
A genuinely self-trained supervised ML model (NOT an LLM call) that
learns to predict a question's TOPIC from its text, trained entirely
on your own pyq_database.csv using scikit-learn.

This directly reuses Day 1 syllabus skills (supervised learning,
train/test split, model evaluation) applied to a real, useful task:
auto-tagging a freshly pasted question with its likely topic, so a
teacher can drop in a new question without manually labelling it.

Train it with:
    python train_classifier.py

Then use predict_topic() anywhere in the app.
"""

import io
import math
import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
from sklearn.pipeline import Pipeline

from .storage import get_object_bytes, put_object, list_objects

MODEL_OBJECT_KEY = "models/topic_classifier.joblib"


def train_topic_classifier(df: pd.DataFrame, save: bool = True) -> dict:
    """
    Trains a TF-IDF + Logistic Regression pipeline to predict `topic`
    from `question_text`. Returns a small report dict so the app can
    display real accuracy numbers to evaluators -- not a canned claim.
    """
    required = {"question_text", "topic"}
    if not required.issubset(df.columns):
        raise ValueError("Classifier training data must include question_text and topic columns.")
    clean = df.dropna(subset=["question_text", "topic"]).copy()
    clean["question_text"] = clean["question_text"].astype(str).str.strip()
    clean["topic"] = clean["topic"].astype(str).str.strip()
    clean = clean[(clean["question_text"] != "") & (clean["topic"] != "")]
    if len(clean) < 4 or clean["topic"].nunique() < 2:
        raise ValueError("Need at least four labeled questions across two topics to train a classifier.")

    X = clean["question_text"]
    y = clean["topic"]
    test_count = max(1, math.ceil(len(clean) * 0.25))
    can_stratify = (
        y.value_counts().min() >= 2
        and test_count >= y.nunique()
        and len(clean) - test_count >= y.nunique()
    )
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y if can_stratify else None
    )
    if y_train.nunique() < 2:
        raise ValueError("The training split contains fewer than two topics. Add more labeled questions and retry.")

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1)),
        ("clf", LogisticRegression(max_iter=1000)),
    ])
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    report = classification_report(y_test, y_pred, zero_division=0)

    if save:
        artifact = io.BytesIO()
        joblib.dump(pipeline, artifact)
        put_object(MODEL_OBJECT_KEY, artifact.getvalue(), original_name="topic_classifier.joblib",
                   category="model", content_type="application/octet-stream")

    return {
        "accuracy": acc,
        "report": report,
        "train_size": len(X_train),
        "test_size": len(X_test),
        "classes": sorted(y.unique().tolist()),
    }


def load_topic_classifier():
    if not any(item["object_key"] == MODEL_OBJECT_KEY for item in list_objects("model")):
        return None
    return joblib.load(io.BytesIO(get_object_bytes(MODEL_OBJECT_KEY)))


def predict_topic(question_text: str) -> dict:
    """
    Predicts the likely topic of a new, freely pasted question using
    the self-trained model -- no AI/LLM call involved here at all.
    """
    if not isinstance(question_text, str) or not question_text.strip():
        return {"error": "Enter a non-empty question to classify."}
    model = load_topic_classifier()
    if model is None:
        return {"error": "Model not trained yet. Run: python train_classifier.py"}

    pred = model.predict([question_text])[0]
    proba = model.predict_proba([question_text])[0]
    classes = model.named_steps["clf"].classes_
    confidence = dict(sorted(zip(classes, proba), key=lambda x: -x[1]))

    return {
        "predicted_topic": pred,
        "confidence": {k: round(float(v), 3) for k, v in list(confidence.items())[:3]},
    }
