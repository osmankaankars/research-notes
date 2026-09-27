terraform {
  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "3.7.2"
    }
    cell = {
      source  = "example/cell"
      version = "0.1.0"
    }
  }
}
variable "red_socket" { type = string }
variable "red_token" { type = string }
variable "blue_socket" { type = string }
variable "blue_token" { type = string }
variable "unassigned_canary" { type = string }

provider "random" {}
provider "cell" {
  alias                   = "red"
  socket_path             = var.red_socket
  token_file              = var.red_token
  unassigned_canary_path   = var.unassigned_canary
}
provider "cell" {
  alias                   = "blue"
  socket_path             = var.blue_socket
  token_file              = var.blue_token
  unassigned_canary_path   = var.unassigned_canary
}
resource "random_id" "anchor" { byte_length = 8 }
resource "cell_record" "red" {
  provider = cell.red
  upstream = random_id.anchor.hex
}
resource "cell_record" "blue" {
  provider = cell.blue
  upstream = cell_record.red.id
}
output "dependency_result" {
  value = {
    anchor        = random_id.anchor.hex
    red_id        = cell_record.red.id
    red_upstream  = cell_record.red.upstream
    blue_id       = cell_record.blue.id
    blue_upstream = cell_record.blue.upstream
    red_checks    = jsondecode(cell_record.red.checks_json)
    blue_checks   = jsondecode(cell_record.blue.checks_json)
  }
}
