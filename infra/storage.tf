# GCS buckets.
#
# Etapa 1: import the existing reports bucket (versioning, public access
# prevention, the objectAdmin binding to the agent SA).
# Etapa 2: declare the data bucket (var.data_bucket) that replaces S3 for raw +
# bronze, with lifecycle mirroring 01_aws_s3.sh (raw → Nearline @30d + expire
# noncurrent @90d; bronze noncurrent @365d).
#
# Resources land here in Etapa 1/2.
