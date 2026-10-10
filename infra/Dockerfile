FROM public.ecr.aws/lambda/python:3.12
COPY python/ ${LAMBDA_TASK_ROOT}/
COPY application/ ${LAMBDA_TASK_ROOT}/
CMD ["compliancelens.handlers.query_handler"]
