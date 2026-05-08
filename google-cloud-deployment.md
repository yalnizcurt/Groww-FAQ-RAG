# Google Cloud Deployment Guide: Groww MF FAQ Assistant

This guide explains how to deploy the application to **Google Cloud Run**. Cloud Run is ideal for this project as it's fully managed, scales automatically, and only charges you when requests are being processed.

## Prerequisites

1.  **Google Cloud Project**: Create one at the [GCP Console](https://console.cloud.google.com/).
2.  **gcloud CLI**: Install it on your local machine ([instructions](https://cloud.google.com/sdk/docs/install)).
3.  **Billing Enabled**: Ensure your project has an active billing account.
4.  **MongoDB**: Since the bot logs interactions to MongoDB, you'll need a connection string. We recommend [MongoDB Atlas (Free Tier)](https://www.mongodb.com/cloud/atlas/register).

---

## 1. Initial Setup

Open your terminal in the project root and run:

```bash
# Login to Google Cloud
gcloud auth login

# Set your project ID
gcloud config set project [YOUR_PROJECT_ID]

# Enable necessary services
gcloud services enable \
    run.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com
```

## 2. Create Artifact Registry

Create a repository to store your Docker images:

```bash
gcloud artifacts repositories create groww-faq-repo \
    --repository-format=docker \
    --location=us-central1 \
    --description="Docker repository for Groww FAQ Assistant"
```

## 3. Build and Deploy

We'll use **Google Cloud Build** to build your image remotely and then deploy it to **Cloud Run**.

Replace the environment variables in the command below with your actual keys and MongoDB URL.

```bash
# Build the image using Cloud Build
gcloud builds submit --tag us-central1-docker.pkg.dev/[YOUR_PROJECT_ID]/groww-faq-repo/assistant:latest .

# Deploy to Cloud Run
gcloud run deploy groww-mf-assistant \
    --image us-central1-docker.pkg.dev/[YOUR_PROJECT_ID]/groww-faq-repo/assistant:latest \
    --platform managed \
    --region us-central1 \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --set-env-vars="GROQ_API_KEY=[YOUR_GROQ_KEY],MONGO_URL=[YOUR_MONGO_URL],DB_NAME=mf_faq,GROQ_MODEL=llama-3.3-70b-versatile,CORS_ORIGINS=*"
```

> [!IMPORTANT]
> **Resource Requirements**: We've set `--memory 2Gi` and `--cpu 2`. This is necessary because the application loads ML models (Sentence Transformers and Cross-Encoder) into memory.

## 4. Environment Variables

| Variable | Description |
| :--- | :--- |
| `GROQ_API_KEY` | Your Groq API key for conversational generation. |
| `MONGO_URL` | Connection string for MongoDB (e.g., `mongodb+srv://...`). |
| `DB_NAME` | Database name for logs (default: `mf_faq`). |
| `GROQ_MODEL` | The Groq model to use (default: `llama-3.3-70b-versatile`). |

## 5. Verifying Deployment

Once the deployment completes, `gcloud` will provide a **Service URL** (e.g., `https://groww-mf-assistant-xyz.a.run.app`).

1.  Open the URL in your browser.
2.  The React frontend should load immediately.
3.  Ask a question like "What is the expense ratio of HDFC Mid Cap Fund?" to verify the backend is processing correctly.

## 6. Continuous Deployment (Optional)

You can connect your GitHub repository to Cloud Run for automatic deployments whenever you push to `main`. Go to the [Cloud Run Console](https://console.cloud.google.com/run), select your service, and click **"SET UP CONTINUOUS DEPLOYMENT"**.
