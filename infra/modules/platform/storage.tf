resource "aws_s3_bucket" "artifacts" {
  for_each = { raw = local.names.raw_bucket, intermediate = local.names.intermediate_bucket }
  bucket   = each.value
}
resource "aws_s3_bucket_versioning" "artifacts" {
  for_each = aws_s3_bucket.artifacts
  bucket   = each.value.id
  versioning_configuration { status = "Enabled" }
}
