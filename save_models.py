import pandas as pd
import numpy as np
import joblib
import os
import mysql.connector
from sklearn.linear_model import LogisticRegression
from sklearn.cluster import KMeans
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from db_config import DB_CONFIG

os.makedirs("models", exist_ok=True)

conn = mysql.connector.connect(**DB_CONFIG)
df = pd.read_sql("SELECT * FROM students", conn)
conn.close()

df["previous_sgpa_clean"] = df["previous_sgpa"].replace(0, np.nan)
df["current_cgpa_clean"] = df["current_cgpa"].replace(0, np.nan)

def compute_at_risk(row):
    if pd.notna(row["current_cgpa_clean"]) and row["current_cgpa_clean"] < 2.5:
        return 1
    if row["attendance_pct"] < 75:
        return 1
    if row["probation"] == "Yes":
        return 1
    return 0

df["at_risk_fixed"] = df.apply(compute_at_risk, axis=1)

# ============ RISK MODEL ============
ml_features = ["attendance_pct", "study_hours", "social_media_hours", "credits_completed", "previous_sgpa_clean"]
ml_data = df.dropna(subset=ml_features + ["at_risk_fixed"])
X = ml_data[ml_features]
y = ml_data["at_risk_fixed"]

risk_model = LogisticRegression(class_weight="balanced", max_iter=1000)
risk_model.fit(X, y)

joblib.dump(risk_model, "models/risk_model.pkl")
joblib.dump(ml_features, "models/risk_features.pkl")
joblib.dump(float(df["previous_sgpa_clean"].median()), "models/sgpa_median.pkl")
print("Saved risk_model.pkl")

# ============ ENGAGEMENT MODEL ============
engagement_features = ["study_hours", "social_media_hours", "attendance_pct"]
eng_data = df.dropna(subset=engagement_features).copy()

scaler = StandardScaler()
X_eng_scaled = scaler.fit_transform(eng_data[engagement_features])

kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
eng_data["cluster"] = kmeans.fit_predict(X_eng_scaled)

cluster_scores = eng_data.groupby("cluster").apply(
    lambda g: g["study_hours"].mean() - g["social_media_hours"].mean() + g["attendance_pct"].mean() / 20,
    include_groups=False,
)
ordered_clusters = cluster_scores.sort_values().index.tolist()
label_map = {ordered_clusters[0]: "Low Engagement", ordered_clusters[1]: "Moderate Engagement", ordered_clusters[2]: "High Engagement"}
eng_data["engagement_level"] = eng_data["cluster"].map(label_map)

mlp = MLPClassifier(hidden_layer_sizes=(16, 8), max_iter=1000, random_state=42)
mlp.fit(X_eng_scaled, eng_data["engagement_level"])

joblib.dump(mlp, "models/engagement_model.pkl")
joblib.dump(scaler, "models/engagement_scaler.pkl")
joblib.dump(engagement_features, "models/engagement_features.pkl")
print("Saved engagement_model.pkl and engagement_scaler.pkl")

print("\nAll models saved to the 'models' folder. These will be loaded by app.py for live predictions on new registrations.")
