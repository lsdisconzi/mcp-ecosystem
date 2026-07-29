# Project Overview: Legal Intelligence & Digital Refuge System

## 1. Vision & Purpose
This project was born from a commitment to turn a difficult experience with systemic injustice into a constructive tool for good. It is a **Retrieval-Augmented Generation (RAG)** system designed to act as a "digital refuge" for individuals and legal professionals navigating the complex, often overwhelming "storm" of legal and regulatory data.

## 2. Core Problem
Complex systems (like the Brazilian legal and aviation regulatory frameworks) often create barriers to entry. People "fall away" because the data is unstructured, the language is dense, and finding relevant precedents is technically exhausting.

## 3. Technical Architecture
*   **Vector Database**: [Qdrant](https://qdrant.tech/) for high-performance semantic search.
*   **NLP Engine**: [NeuralMind BERT-Base-Portuguese](https://github.com/neuralmind-ai/portuguese-bert) for deep linguistic understanding of Brazilian legal nuances.
*   **Ingestion Pipeline**: A custom, section-aware processor that handles `.doc`, `.docx`, and `.pdf`, preserving the human structure of legal decisions (Header, Report, Vote, Decision).
*   **Metadata Intelligence**: Automatic extraction and indexing of:
    *   **Cited Legislation**: (e.g., CDC, ANAC Resolution 400, Civil Code Art. 932).
    *   **Jurisprudence**: Cross-referencing previous court decisions (STJ, TJRS, etc.).
    *   **Entities**: Identifying judges (Relatores), courts, and parties.

## 4. Key Features
*   **Semantic Search**: Finds "meaning" rather than just keywords (e.g., searching for "verbal aggression by employee" finds relevant cases even if those exact words aren't used).
*   **Case-Insensitive Filtering**: A robust normalization layer that allows users to filter by law citations regardless of formatting.
*   **Section-Aware Retrieval**: Allows the system to answer questions based on specific parts of a document (e.g., "What was the judge's reasoning in the Vote section?").

## 5. Current Impact
The system is currently being used to support the **LATAM / André BD Marinho** case, specifically targeting violations of consumer rights and airline liability. It has successfully identified high-value jurisprudence for:
*   Verbal aggression by airline staff (targeting R$ 15k+ damage precedents).
*   Lack of assistance during flight delays (ANAC 400 violations).
*   The "Método Bifásico" for quantifying moral damages.

## 6. The "Art of the Possible"
This project demonstrates that technology can be a supportive, human-centric tool. By automating the "heavy lifting" of legal research, we provide a refuge where the focus returns to **inner truth and justice** rather than technical frustration.
