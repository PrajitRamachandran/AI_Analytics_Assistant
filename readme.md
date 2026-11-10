AI Data Analytics Assistant — V1 MVP Project Overview

Project Progress

Current Status: Modules 1, 2 and 3 of 7 completed.

-   Module 1: Excel Upload — Completed. Backend upload API, React upload
    interface, file validation, upload history, PostgreSQL metadata
    storage, file download and deletion have been implemented and
    tested.
-   Module 2: Excel Ingestion, Parsing, Normalisation and Cleaning —
    Completed. Multi-worksheet ingestion, column-name normalisation,
    conservative data cleaning, processing API integration and frontend
    processing results have been implemented and tested.
-   Module 3: Data Understanding Engine — Completed. Dataset profiling,
    column-level data type identification, statistical summaries,
    category frequencies, missing-value and duplicate analysis, and
    structured dataset profile output have been implemented and
    integrated with the frontend.
-   Progress so far: The application can upload and manage Excel
    workbooks, ingest multiple worksheets, normalise column names,
    identify data-quality issues, remove fully empty rows and columns,
    detect duplicate rows, and display per-worksheet processing
    summaries and data previews. It can also profile processed worksheets,
    identify column types and potential semantic roles, calculate basic
    statistics, and display worksheet and column-level data understanding
    results. Processed DataFrames are currently held in memory for the
    processing workflow; the original workbook remains unchanged.
-   Module 4: AI Analytics Planner — Pending.
-   Module 5: Analytics Execution Engine — Pending.
-   Module 6: Dashboard Generation and Report Downloading — Pending.
-   Module 7: Chat Engine — Pending.

1. Project Objective

Build a simple AI-powered analytics application that allows users to
upload Excel files and automatically generates a meaningful, interactive
dashboard based on the data.

The application should understand the uploaded dataset, identify useful
metrics and patterns, perform relevant calculations, generate
visualisations and reports, and allow users to ask basic questions about
their data through a chat interface.

The goal is to build a functional MVP, not a production-ready or
deployment-focused system. The architecture should be modular, with each
module having a clear responsibility.

2. Overall Workflow

1. Excel Upload

User uploads an Excel workbook through React

2. Excel Ingestion and Processing

Read worksheets, parse, normalise and clean data

3. Data Understanding Engine

Understand columns, data types, statistics and dataset structure

4. AI Analytics Planner

Use the dataset profile to decide what should be analysed

5. Analytics Execution Engine

Perform actual calculations using Python

6. Dashboard and Reports

Visualise results and download PDF reports

7. Chat Engine

Answer questions about the uploaded dataset

3. Module-wise Description

Module 1: Excel Upload

Purpose: Provide a simple interface for users to upload Excel workbooks.

What it does:

-   Allows users to select and upload .xlsx and, if supported, .xls
    files.
-   Displays the selected filename and upload status.
-   Sends the file to the Python backend.
-   Displays basic validation errors if the file is invalid or
    unsupported.
-   Displays upload history, including previously uploaded files and
    their details.
-   Stores uploaded file metadata in PostgreSQL.
-   Allows users to download previously uploaded Excel files.
-   Allows users to delete uploaded files and their corresponding
    metadata.
-   Validates file size, with a maximum upload limit of 25 MB.
-   Validates uploaded workbook structure and readability.

How it works:

1.  User selects an Excel file through the React interface.
2.  React sends the file to a FastAPI upload endpoint using a multipart
    form request.
3.  FastAPI receives the file, validates it and stores it in the backend
    uploads directory.
4.  The backend stores the file metadata in PostgreSQL.
5.  The backend returns an upload status and dataset identifier.
6.  React refreshes the upload history to display the newly uploaded
    file.
7.  Users can download or delete files directly from the upload history.

Tech stack:

-   Frontend: React, JavaScript, Tailwind CSS.
-   Backend: Python, FastAPI.
-   Database: PostgreSQL.
-   Communication: Axios.

Expected output: An uploaded Excel workbook ready for processing, with
persistent upload history and basic file management functionality.

Module 2: Excel Ingestion, Parsing, Normalisation and Cleaning

Purpose: Read the uploaded Excel workbook, extract its data and prepare
it for analysis.

What it does:

-   Reads Excel workbooks and extracts data from individual worksheets.
-   Handles multiple worksheets within a workbook.
-   Identifies headers and converts worksheets into structured tabular
    data.
-   Normalises column names and basic data formats.
-   Handles missing values, duplicate rows, empty rows and empty
    columns.
-   Identifies inconsistent data formats where possible.
-   Performs basic validation and reports processing errors.
-   Maintains worksheet names and their corresponding datasets.
-   Preserves the original-to-normalised column-name mapping and ensures
    normalized column names are unique, including when multiple original
    headers normalize to the same base name.
-   Removes fully empty rows and columns while preserving non-empty
    records and values.
-   Reports missing-value counts and percentages, whitespace-padded
    values, mixed data types and duplicate-row counts; duplicate rows
    are identified but retained by default.
-   Produces per-worksheet processing summaries, column metadata and
    data previews, and reports worksheet-level processing errors.

How it works:

1.  The ingestion module receives the uploaded Excel file.
2.  Pandas reads the workbook and extracts individual worksheets.
3.  Each worksheet is converted into a Pandas DataFrame.
4.  Basic cleaning and normalisation operations are performed.
5.  The processed worksheets are stored in memory in a structured format
    for the next module.
6.  A workbook-processing orchestrator runs ingestion, normalisation and
    cleaning in sequence.
7.  A FastAPI processing endpoint makes the workflow available to the
    React frontend and returns worksheet summaries, column metadata,
    cleaning statistics, previews and any worksheet errors.
8.  The frontend displays the processing results for each worksheet, and
    the dataset status is updated to processed after successful
    processing.

For example:

An Excel workbook containing Sales, Employees and Products worksheets
will be read and processed as three separate DataFrames.

The original file should remain unchanged. Cleaning should not silently
remove meaningful information; missing values and duplicates should be
handled carefully and reported.

Tech stack:

-   Python.
-   Pandas.
-   OpenPyXL.
-   xlrd (if legacy .xls support is required).

Expected output: Cleaned and structured DataFrames representing the
workbook’s worksheets.

Module 3: Data Understanding Engine

Purpose: Understand the structure and characteristics of the uploaded
dataset before sending it to the AI Analytics Planner.

This module should be simple and functional. It does not need complex
machine learning models or an elaborate data profiling framework.

What it does:

-   Identifies the number of rows and columns.
-   Identifies column names and data types.
-   Distinguishes numerical, categorical, date and text columns.
-   Calculates basic statistical information.
-   Identifies missing values and duplicate records.
-   Identifies unique values and frequently occurring categories.
-   Identifies potential date, amount, quantity and identifier columns.
-   Generates a structured summary of the dataset.
-   Displays worksheet-level profiling summaries and column-level details
    in the frontend, including inferred semantic roles, statistics,
    frequent categories and data-quality indicators.

How it works:

The module receives the processed DataFrames from the ingestion module
and uses Pandas to inspect and profile the data.

For example, consider an uploaded sales dataset:

  Column       Inferred type   Possible meaning
  ------------ --------------- ------------------
  Order_ID     Identifier      Order reference
  Product      Categorical     Product name
  Region       Categorical     Sales region
  Order_Date   Date            Transaction date
  Quantity     Numerical       Units sold
  Revenue      Numerical       Sales amount

The engine calculates relevant statistics such as:

-   Total records.
-   Total revenue.
-   Average revenue.
-   Minimum and maximum values.
-   Unique product and region counts.
-   Missing value counts.
-   Date ranges.

It then combines these findings into a structured dataset profile,
preferably JSON.

Tech stack:

-   Python.
-   Pandas.
-   NumPy.
-   Pydantic (for structuring and validating the output).

Expected output: A structured dataset profile containing worksheet
information, column details, data types, statistics and basic data
quality information.

Module 4: AI Analytics Planner

Purpose: Use the dataset profile to understand the business context and
decide what analytics should be performed.

This is where the local LLM comes into the application.

What it does:

-   Analyses the dataset profile generated by the Data Understanding
    Engine.
-   Identifies the likely context of the dataset, such as sales,
    finance, HR, inventory or attendance.
-   Interprets column meanings using their names, types and available
    statistics.
-   Identifies useful KPIs and metrics.
-   Suggests relevant comparisons, trends and aggregations.
-   Decides which charts and visualisations would be useful.
-   Generates a structured analytical plan for the Analytics Execution
    Engine.

How it works:

1.  The planner receives the structured dataset profile.
2.  The profile is passed to a locally running LLM.
3.  The LLM interprets the dataset and suggests relevant analytical
    operations.
4.  The LLM returns a structured JSON response describing the KPIs,
    calculations and visualisations required.
5.  The backend validates the response before passing it to the
    execution engine.

For example, if the uploaded dataset contains sales information, the
planner might suggest:

-   Total revenue.
-   Total quantity sold.
-   Revenue by product.
-   Revenue by region.
-   Monthly revenue trend.
-   Top-performing products.

The important distinction is that the LLM decides what to analyse, but
it does not perform the actual calculations.

It should return structured instructions rather than generate and
execute arbitrary Python code.

Tech stack:

-   Python.
-   Ollama for local LLM execution.
-   A suitable local instruct model, selected based on available
    hardware.
-   HTTPX for communicating with Ollama.
-   Pydantic for validating the generated analytical plan.

Expected output: A validated analytical plan containing KPIs,
calculations, groupings and recommended visualisations.

Module 5: Analytics Execution Engine

Purpose: Execute the analytical plan generated by the AI Analytics
Planner and produce accurate numerical results.

What it does:

-   Calculates KPIs.
-   Performs aggregations and groupings.
-   Calculates sums, averages, counts, minimums and maximums.
-   Identifies top and bottom performers.
-   Performs date-based aggregations and trend calculations.
-   Generates chart-ready datasets.
-   Handles invalid operations and missing columns.

How it works:

1.  Receives the validated analytical plan.
2.  Identifies the required worksheets and columns.
3.  Executes the requested operations using Pandas and NumPy.
4.  Validates the results and handles calculation errors.
5.  Returns the results in a structured JSON format.

For example, if the planner requests revenue by region, the execution
engine performs a group-by operation on the Region column and calculates
the sum of Revenue.

The execution engine is responsible for actual calculations. The LLM
must not invent or estimate numerical results.

Tech stack:

-   Python.
-   Pandas.
-   NumPy.
-   Pydantic.

Expected output: Accurate analytical results, KPI values and chart-ready
datasets.

Module 6: Dashboard Generation and Report Downloading

Purpose: Convert the analytical results into a dynamic dashboard and
allow users to download an analytical report.

What it does:

-   Generates KPI cards.
-   Displays charts and graphs based on the analytical plan.
-   Displays relevant tables and summaries.
-   Shows key findings and insights.
-   Adapts the dashboard to the uploaded dataset rather than using a
    fixed dashboard template.
-   Allows users to download a PDF report containing the analysis.

How it works:

Dashboard generation:

1.  Receives the analytical plan and execution results.
2.  Backend generates a structured dashboard configuration in JSON.
3.  The configuration specifies KPI cards, chart types, titles, labels
    and corresponding data.
4.  React receives the configuration and dynamically renders the
    dashboard.
5.  Reusable React components display the KPIs, charts, tables and
    insights.

For example:

-   Sales dataset → Revenue cards, regional sales charts and monthly
    trends.
-   HR dataset → Employee count, department distribution and salary
    analysis.
-   Inventory dataset → Stock levels, product distribution and inventory
    summaries.

Report generation:

1.  The backend receives the verified analytical results.
2.  It prepares a report containing dataset information, KPIs, charts
    and key findings.
3.  Python generates a PDF document.
4.  The frontend provides a download option.

Tech stack:

-   Frontend: React, Recharts, Tailwind CSS.
-   Backend: Python, FastAPI.
-   PDF generation: ReportLab.
-   Report charts: Matplotlib.

Expected output: A dynamic interactive dashboard and a downloadable PDF
analytics report.

Module 7: Chat Engine

Purpose: Allow users to interact with their uploaded dataset through a
basic conversational interface.

The V1 chat functionality should support simple questions about the
dataset and its analytical results. Advanced RAG, multi-agent workflows
and complex reasoning are outside the MVP scope.

What it does:

-   Answers questions about the uploaded dataset.
-   Explains column names and their possible meanings.
-   Answers basic questions about data structure and quality.
-   Explains dashboard KPIs and visualisations.
-   Handles simple numerical questions using the Analytics Execution
    Engine.
-   Supports basic follow-up questions using recent conversation
    context.

How it works:

1.  User enters a question through the React chat interface.
2.  The question is sent to a FastAPI chat endpoint.
3.  The Chat Engine receives the dataset profile, relevant analytical
    results and recent conversation history.
4.  The local LLM interprets the question.
5.  If the question requires a numerical calculation, the Chat Engine
    requests the appropriate operation from the Analytics Execution
    Engine.
6.  The LLM converts the verified result into a natural-language
    response.
7.  The response is displayed in the chat interface.

For example:

  -----------------------------------------------------------------------
  User question                   Expected behaviour
  ------------------------------- ---------------------------------------
  What is this dataset about?     Explain the dataset context

  How many records are there?     Return the row count

  Which product generated the     Execute a calculation and return the
  highest revenue?                result

  What is the average revenue?    Calculate and explain the result

  What does the Revenue column    Explain its likely meaning based on
  represent?                      available evidence
  -----------------------------------------------------------------------

The Chat Engine and AI Analytics Planner can use the same local LLM
service, but they have different responsibilities.

Tech stack:

-   Frontend: React.
-   Backend: Python, FastAPI.
-   AI: Ollama and a local instruct model.
-   Data processing: Pandas.
-   HTTP communication: HTTPX.

Expected output: A working chat interface that answers basic questions
about the uploaded dataset using actual dataset information and verified
calculations.

4. Technology Stack — Consolidated

  Layer               Technology
  ------------------- ------------------------------
  Frontend            React, JavaScript, Vite
  UI styling          Tailwind CSS
  Charts              Recharts
  API communication   Axios
  Backend             Python, FastAPI, Uvicorn
  Excel processing    Pandas, OpenPyXL
  Data analysis       Pandas, NumPy
  AI / LLM            Ollama, local instruct model
  LLM communication   HTTPX
  Data validation     Pydantic
  PDF generation      ReportLab
  Report charts       Matplotlib
  Development         VS Code, Git, Postman

5. Module Interaction and Data Flow

The modules should communicate through clearly defined inputs and
outputs. Avoid tightly coupling the modules or making one module
responsible for everything.

  -----------------------------------------------------------------------
  Module             Receives                   Produces
  ------------------ -------------------------- -------------------------
  Excel Upload       User-selected workbook     Uploaded file

  Excel Ingestion    Uploaded file              Processed worksheet
                                                DataFrames

  Data Understanding Processed DataFrames       Dataset profile

  AI Analytics       Dataset profile            Analytical plan
  Planner                                       

  Analytics          Analytical plan +          Verified analytical
  Execution          DataFrames                 results

  Dashboard and      Plan + analytical results  Dashboard configuration +
  Reports                                       PDF

  Chat Engine        User question + dataset    Natural-language answer
                     context                    
  -----------------------------------------------------------------------

6. Important MVP Scope Boundaries

To keep the project manageable, V1 should focus on the following:

Included:

-   Excel file upload and processing.
-   Multiple worksheet handling.
-   Basic data cleaning and normalisation.
-   Automated dataset understanding.
-   Local LLM-based analytics planning.
-   Actual analytical calculations using Python.
-   Dynamic dashboard generation.
-   Basic PDF report downloading.
-   Basic conversational analytics.

Not included in V1:

-   PDF, Word, PowerPoint or Power BI file ingestion.
-   Google Sheets integration.
-   Vector databases or advanced RAG pipelines.
-   Multiple AI agents.
-   Power BI dashboard creation.
-   Advanced forecasting and predictive modelling.
-   Cloud LLM integration.
-   Production deployment, authentication and enterprise-level
    infrastructure.

Overall design principle: Keep the system modular and straightforward.
Python handles data processing and calculations, the local LLM handles
interpretation and planning, and React handles dashboard visualisation
and user interaction. Each module should perform one clearly defined
task and pass its output to the next module.

The result should be a working MVP where a user uploads an Excel
workbook, receives a dashboard tailored to its contents, downloads a PDF
report and asks basic questions about the data.