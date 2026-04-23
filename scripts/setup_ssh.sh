#!/bin/bash
# ORCA SSH Setup
which ssh >/dev/null 2>&1 || apt-get install -y -qq openssh-client
mkdir -p ~/.ssh
echo 'LS0tLS1CRUdJTiBPUEVOU1NIIFBSSVZBVEUgS0VZLS0tLS0KYjNCbGJuTnphQzFyWlhrdGRqRUFBQUFBQkc1dmJtVUFBQUFFYm05dVpRQUFBQUFBQUFBQkFBQUFNd0FBQUF0emMyZ3RaVwpReU5UVXhPUUFBQUNBL0NlWHV2Vm5jZWxWU2dFcXRDV0FJMG5uV005a0FNTlM1d0daMVc5ZEhlQUFBQUpqcFFrTnA2VUpECmFRQUFBQXR6YzJndFpXUXlOVFV4T1FBQUFDQS9DZVh1dlZuY2VsVlNnRXF0Q1dBSTBubldNOWtBTU5TNXdHWjFXOWRIZUEKQUFBRUFNcTFxSlR6V1pRamJzVWhiSzRHQjhPQmxFdzVBU2llZ3djU1ZvZ1B1UzR6OEo1ZTY5V2R4NlZWS0FTcTBKWUFqUwplZFl6MlFBdzFMbkFablZiMTBkNEFBQUFEbTl5WTJFdFkya3RaR1Z3Ykc5NUFRSURCQVVHQnc9PQotLS0tLUVORCBPUEVOU1NIIFBSSVZBVEUgS0VZLS0tLS0K' | base64 -d > ~/.ssh/orca_deploy_key
chmod 600 ~/.ssh/orca_deploy_key
ORCA_IP=$(curl -s "https://api.digitalocean.com/v2/droplets?tag_name=orca" \
  -H "Authorization: Bearer dop_v1_60651458efb36ecb98f382f8f8daa19a086bf4f8444f93ad98d84541258b174d" | \
  python3 -c "import json,sys; drops=json.load(sys.stdin).get('droplets',[]); pub=[n for n in drops[0]['networks']['v4'] if n['type']=='public'] if drops else []; print(pub[0]['ip_address'] if pub else 'NOT_FOUND')" 2>/dev/null)
export ORCA_IP
echo "ORCA_IP=$ORCA_IP"
echo "Patch: ssh -i ~/.ssh/orca_deploy_key -o StrictHostKeyChecking=no root@$ORCA_IP 'cd /opt/orca && git pull origin main && docker-compose restart && echo DONE'"
