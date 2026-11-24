#!/usr/bin/env python3
import os

import aws_cdk as cdk

from potty_train_stack import PottyTrainStack

app = cdk.App()
PottyTrainStack(
    app,
    "PottyTrain",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
    description="Potty training log: private S3 data, Lambda API, CloudFront site limited to an IP allowlist.",
)
app.synth()
