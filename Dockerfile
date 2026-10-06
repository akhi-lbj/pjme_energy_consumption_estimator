# 1. Use the private AWS Lambda Python base image hosted in your registry
FROM 138071776345.dkr.ecr.ap-south-1.amazonaws.com/lambda/python:3.12

# 2. Copy the dependencies list into the container
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# 3. Install the application dependencies (including your new boto3 library)
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy your FastAPI application code and the scikit-learn models folder
COPY app.py ${LAMBDA_TASK_ROOT}
COPY models/ ${LAMBDA_TASK_ROOT}/models/

# 5. Set the entry point handler to map to Mangum inside app.py
CMD [ "app.handler" ]