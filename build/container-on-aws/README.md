# Container Image Builder Action

A composite action to build container image on AWS ECR.

## Usage

### Inputs

- `name`: The container image name [__REQUIRED__].
- `context`: The context to be use during build. It defaults to the current working directory.
- `dockerfile`: Dockerfile path relative to the context. It defaults to `${context}/Dockerfile`.
- `tag`: Tag to be used for the container image [__REQUIRED__].
- `build-role`: The AWS role to assume for building container. It could be in the form of github vars on `env.AWS_BUILD_ROLE`, otherwise it must be provided as input.
- `region`: AWS region to use. It defaults to ap-east-1.

## Examples

### Simple usage

```yaml

jobs:
  build:
    steps:
      - name: Build Container Image
        uses: ardikabs/actions/build/container-on-aws@main
        with:
          name: echoserver
          dockerfile: Dockerfile # refers to ./Dockerfile or current working directory
          tag: v1.0.0
```

### Customizing build context

```yaml

jobs:
  build:
    steps:
      - name: Build Container Image
        uses: ardikabs/actions/build/container-on-aws@main
        with:
          context: path/to/.dockerbuilds
          name: echoserver
          tag: v1.0.0

```