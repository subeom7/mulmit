# AWS 배포

EC2 한 대 + GitHub Actions. **SSH를 열지 않는다** — 셸 접속도 배포도 전부
SSM을 쓴다. 인바운드 포트는 80/443뿐이고 GitHub에 저장하는 AWS 자격증명은
없다(OIDC).

```
git push main
  → Actions: ruff + pytest
  → Actions: ARM 네이티브 빌드 → GHCR
  → Actions: OIDC로 역할 위임 → SSM Send-Command
  → EC2: git checkout <sha> && ./deploy/release.sh <image>
  → 헬스체크 실패 시 직전 이미지로 자동 롤백
```

아래 명령은 전부 로컬에서 `aws` CLI로 실행한다. 리전은 **서울**이다.

```bash
export AWS_REGION=ap-northeast-2
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export GITHUB_REPO="subeom7/mulmit"
```

---

## 1. 인스턴스 역할 (SSM 접속용)

이게 있어야 SSH 없이 관리와 배포가 된다.

```bash
aws iam create-role --role-name stock-metrics-ec2 \
  --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]
  }'

aws iam attach-role-policy --role-name stock-metrics-ec2 \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore

aws iam create-instance-profile --instance-profile-name stock-metrics-ec2
aws iam add-role-to-instance-profile \
  --instance-profile-name stock-metrics-ec2 --role-name stock-metrics-ec2
```

## 2. 보안 그룹

```bash
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)

SG_ID=$(aws ec2 create-security-group --group-name stock-metrics \
  --description "stock metrics web" --vpc-id "$VPC_ID" \
  --query GroupId --output text)

for PORT in 80 443; do
  aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
    --protocol tcp --port $PORT --cidr 0.0.0.0/0
done
echo "SG_ID=$SG_ID"
```

> Cloudflare 프록시(주황 구름)를 켤 거라면 `0.0.0.0/0` 대신 Cloudflare IP
> 대역만 허용하는 게 낫다. 오리진 IP가 알려져도 우회 접속이 막힌다.
> 대역 목록: `https://www.cloudflare.com/ips-v4`

## 3. 인스턴스

```bash
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64" \
  --instance-type t4g.small \
  --security-group-ids "$SG_ID" \
  --iam-instance-profile Name=stock-metrics-ec2 \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":30,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
  --metadata-options 'HttpTokens=required' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=stock-metrics}]' \
  --query 'Instances[0].InstanceId' --output text)

echo "INSTANCE_ID=$INSTANCE_ID"
aws ec2 wait instance-status-ok --instance-ids "$INSTANCE_ID"
```

키페어를 안 넣은 게 맞다. SSH를 안 쓴다.

**탄력적 IP**를 붙여야 재부팅해도 주소가 안 바뀐다:

```bash
ALLOC_ID=$(aws ec2 allocate-address --domain vpc --query AllocationId --output text)
aws ec2 associate-address --instance-id "$INSTANCE_ID" --allocation-id "$ALLOC_ID"
aws ec2 describe-addresses --allocation-ids "$ALLOC_ID" \
  --query 'Addresses[0].PublicIp' --output text
```

이 IP를 DNS의 A 레코드로 지정한다.

## 4. 인스턴스 초기 세팅

SSH 대신 SSM으로 들어간다:

```bash
aws ssm start-session --target "$INSTANCE_ID"
```

들어가서:

```bash
sudo su -
export REPO_URL="https://github.com/subeom7/mulmit.git"
curl -fsSL "https://raw.githubusercontent.com/subeom7/mulmit/main/deploy/bootstrap.sh" | bash
vi /opt/stock-metrics/.env     # DOMAIN, IMAGE 채우기
cd /opt/stock-metrics && docker compose up -d
```

`bootstrap.sh`가 하는 일: docker/git 설치, compose 플러그인, 스왑 2GB,
도커 로그 크기 제한, 저장소 클론, `.env` 생성(POSTGRES_PASSWORD 무작위).

## 5. GitHub OIDC 역할

GitHub Actions가 **장기 자격증명 없이** AWS에 접근하게 한다.

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

cat > /tmp/trust.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:${GITHUB_REPO}:ref:refs/heads/main"
      }
    }
  }]
}
JSON

aws iam create-role --role-name stock-metrics-deploy \
  --assume-role-policy-document file:///tmp/trust.json
```

`sub` 조건이 핵심이다. 이걸 빼면 **아무 GitHub 저장소나** 이 역할을 위임받을
수 있다. `ref:refs/heads/main`으로 못 박아서 main 브랜치 워크플로만 통과한다.

권한은 그 인스턴스 하나에 명령을 보내는 것만:

```bash
cat > /tmp/policy.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ec2:${AWS_REGION}:${ACCOUNT_ID}:instance/${INSTANCE_ID}",
        "arn:aws:ssm:${AWS_REGION}::document/AWS-RunShellScript"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["ssm:ListCommandInvocations", "ssm:GetCommandInvocation"],
      "Resource": "*"
    }
  ]
}
JSON

aws iam put-role-policy --role-name stock-metrics-deploy \
  --policy-name deploy --policy-document file:///tmp/policy.json

echo "AWS_DEPLOY_ROLE_ARN=arn:aws:iam::${ACCOUNT_ID}:role/stock-metrics-deploy"
```

## 6. GitHub 설정

저장소 → Settings → Secrets and variables → Actions:

| 이름 | 값 |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | 위 5번 출력 |
| `EC2_INSTANCE_ID` | 위 3번 출력 |

GHCR 이미지는 저장소가 public이면 별도 인증 없이 EC2에서 받아진다.
Settings → Packages에서 패키지 가시성이 public인지 확인할 것.

## 7. DNS

| 이름 | 유형 | 값 | 프록시 |
|---|---|---|---|
|  `@` 와 `www` | A | 4번의 탄력적 IP | **처음엔 DNS only** |

Caddy가 Let's Encrypt 인증서를 받으려면 80번이 직접 닿아야 한다. 인증서가
발급되고 사이트가 뜬 걸 확인한 다음에 프록시를 켜되, 그때는 `deploy/Caddyfile`
상단의 갱신 함정 설명을 반드시 읽을 것.

## 8. 첫 배포

```bash
git push origin main
```

Actions 탭에서 test → build → deploy가 초록으로 끝나는지 본다.

---

## 운영

```bash
# 셸 접속
aws ssm start-session --target "$INSTANCE_ID"

# 상태
curl https://<도메인>/api/status          # 저장된 티커 수, 마지막 수집 시각
cd /opt/stock-metrics && sudo docker compose ps
sudo docker compose logs -f web ingest

# 수동 수집
sudo docker compose run --rm ingest python -m app.ingest AAPL MSFT

# DB 백업 (cron에 걸어 S3로 보내면 좋다)
sudo docker compose exec -T db pg_dump -U stock stock | gzip > backup.sql.gz
```

## 비용 (서울, 대략)

| 항목 | 월 |
|---|---|
| t4g.small 온디맨드 | ~$15 |
| gp3 30GB | ~$2.7 |
| 탄력적 IP | ~$3.6 |
| 전송·S3 | ~$0.1 |
| **합계** | **~$21 (약 3만원)** |

두세 달 돌려 보고 계속 갈 확신이 서면 1년 Compute Savings Plan으로
EC2가 $15 → $9로 떨어진다. 처음부터 1년 묶지 말 것.

정확한 금액은 결제 전에 AWS Pricing Calculator로 확인하고, 계정이 아직
프리티어면 Billing 콘솔에서 잔여 크레딧부터 볼 것.
