import pandas as pd
import numpy as np
import mysql.connector
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.cluster import KMeans
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report

# ---------- CONFIG ----------
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "root123",   # <-- change this
    "database": "edumentor",
}
# -----------------------------

conn = mysql.connector.connect(**DB_CONFIG)

# ============ 1. LOAD DATA FROM MYSQL ============

df = pd.read_sql("SELECT * FROM students", conn)
print(f"Loaded {len(df)} students from MySQL.")

# ============ 2. HANDLE 0-VALUE SGPA/CGPA (means 'no prior record', not a real 0) ============

df["previous_sgpa_clean"] = df["previous_sgpa"].replace(0, np.nan)
df["current_cgpa_clean"] = df["current_cgpa"].replace(0, np.nan)

no_record_count = df["current_cgpa_clean"].isna().sum()
print(f"{no_record_count} students have no prior CGPA on record (likely first-semester students).")

# ============ 3. RECOMPUTE AT-RISK LABEL PROPERLY ============
# A student with no CGPA record yet can't be flagged risky by CGPA -
# fall back to attendance/probation only for them.

def compute_at_risk(row):
    if pd.notna(row["current_cgpa_clean"]) and row["current_cgpa_clean"] < 2.5:
        return 1
    if row["attendance_pct"] < 75:
        return 1
    if row["probation"] == "Yes":
        return 1
    return 0

df["at_risk_fixed"] = df.apply(compute_at_risk, axis=1)
print(f"At-risk students (corrected): {df['at_risk_fixed'].sum()} out of {len(df)}")

# ============ 4. TRAIN THE ML MODEL (LOGISTIC REGRESSION) ============

ml_features = [
    "attendance_pct",
    "study_hours",
    "social_media_hours",
    "credits_completed",
    "previous_sgpa_clean",
]
ml_data = df.dropna(subset=ml_features + ["at_risk_fixed"])
X = ml_data[ml_features]
y = ml_data["at_risk_fixed"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

risk_model = LogisticRegression(class_weight="balanced", max_iter=1000)
risk_model.fit(X_train, y_train)
y_pred = risk_model.predict(X_test)

print("\n===== ML MODEL: At-Risk Prediction (Logistic Regression) =====")
print("Accuracy:", accuracy_score(y_test, y_pred))
print(confusion_matrix(y_test, y_pred))
print(classification_report(y_test, y_pred))

# Predict for ALL students, including the 39 with no prior SGPA on record -
# fill their missing SGPA with the class median just for prediction purposes
# (they were already trained on real values only, this is prediction-time only).
X_all = df[["attendance_pct", "study_hours", "social_media_hours", "credits_completed"]].copy()
X_all["previous_sgpa_clean"] = df["previous_sgpa_clean"].fillna(df["previous_sgpa_clean"].median())
X_all = X_all.fillna(X_all.median())
df["risk_prediction_new"] = risk_model.predict(X_all[ml_features])

# ============ 5. DEEP LEARNING MODEL: ENGAGEMENT PATTERN ANALYSIS ============
# Step A: use KMeans to DISCOVER natural engagement clusters (unsupervised pattern analysis)
# Step B: train a small neural network (MLPClassifier) to LEARN to predict that cluster
#         from a student's features - this is the "deep learning" component.

engagement_features = ["study_hours", "social_media_hours", "attendance_pct"]
eng_data = df.dropna(subset=engagement_features).copy()

scaler = StandardScaler()
X_eng_scaled = scaler.fit_transform(eng_data[engagement_features])

kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
eng_data["cluster"] = kmeans.fit_predict(X_eng_scaled)

# Label clusters by their average "engagement score" (study - social + attendance/20)
cluster_scores = eng_data.groupby("cluster").apply(
    lambda g: g["study_hours"].mean() - g["social_media_hours"].mean() + g["attendance_pct"].mean() / 20
)
ordered_clusters = cluster_scores.sort_values().index.tolist()
label_map = {ordered_clusters[0]: "Low Engagement", ordered_clusters[1]: "Moderate Engagement", ordered_clusters[2]: "High Engagement"}
eng_data["engagement_level"] = eng_data["cluster"].map(label_map)

print("\n===== Engagement clusters discovered =====")
print(eng_data["engagement_level"].value_counts())

# Train the neural network to predict engagement_level from features
X_train_e, X_test_e, y_train_e, y_test_e = train_test_split(
    X_eng_scaled, eng_data["engagement_level"], test_size=0.2, random_state=42, stratify=eng_data["engagement_level"]
)

engagement_model = MLPClassifier(hidden_layer_sizes=(16, 8), max_iter=1000, random_state=42)
engagement_model.fit(X_train_e, y_train_e)
y_pred_e = engagement_model.predict(X_test_e)

print("\n===== DEEP LEARNING MODEL: Engagement Pattern Classifier (Neural Network) =====")
print("Accuracy:", accuracy_score(y_test_e, y_pred_e))
print(classification_report(y_test_e, y_pred_e))

# Predict engagement level for ALL students with complete data
eng_data["engagement_level_pred"] = engagement_model.predict(X_eng_scaled)

# ============ 6. WRITE PREDICTIONS BACK TO MYSQL ============

cursor = conn.cursor()

update_risk_sql = "UPDATE students SET risk_prediction = %s WHERE student_id = %s"
risk_updates = list(zip(df["risk_prediction_new"].astype(int), df["student_id"]))
cursor.executemany(update_risk_sql, risk_updates)

update_engagement_sql = "UPDATE students SET engagement_level = %s WHERE student_id = %s"
engagement_updates = list(zip(eng_data["engagement_level_pred"], eng_data["student_id"]))
cursor.executemany(update_engagement_sql, engagement_updates)

conn.commit()
print(f"\nUpdated risk_prediction for {len(risk_updates)} students.")
print(f"Updated engagement_level for {len(engagement_updates)} students.")

cursor.close()
conn.close()
print("Done. MySQL 'students' table now has both model outputs.")
