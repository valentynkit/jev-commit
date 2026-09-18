"""Twenty config-shaped credential cases, eleven secrets and nine not.

Written here rather than lifted from teyhouse/jev-secret-detection, whose fixture file has
no license at all (`gh api repos/teyhouse/jev-secret-detection --jq .license` is null), so
its 20 cases cannot be redistributed. Same shape as theirs, same idea: low entropy, no
vendor prefix, a real config format, and pairs that share a file and a field and differ
only in the value. Every value was invented for this file and has never been valid.

The comparison against their published 15/20 is therefore indicative, not like for like:
different sets, same class of case.
"""

CASES = [
    ("cfg_001", "roles/mail/files/msmtprc", True, "password",
     "account larkspur\nhost smtp.larkspur.internal\nport 587\nuser alerts@larkspur.internal\n"
     "password Relay-Larkspur-7719\n"),
    ("cfg_002", "roles/mail/files/msmtprc", False, "reference",
     "account larkspur\nhost smtp.larkspur.internal\nport 587\nuser alerts@larkspur.internal\n"
     'passwordeval "pass show smtp/larkspur/alerts"\n'),
    ("cfg_003", "etc/nslcd.conf", True, "password",
     "uri ldaps://ldap.larkspur.internal\nbase dc=larkspur,dc=internal\n"
     "binddn cn=nslcd,ou=service,dc=larkspur,dc=internal\nbindpw Svc-Ldap-Bind-7742\nssl on\n"),
    ("cfg_004", "etc/nslcd.conf", False, "reference",
     "uri ldaps://ldap.larkspur.internal\nbase dc=larkspur,dc=internal\n"
     "binddn cn=nslcd,ou=service,dc=larkspur,dc=internal\nbindpw_file /etc/nslcd.secret\nssl on\n"),
    ("cfg_005", "deploy/pgbouncer/userlist.txt", True, "password",
     '"reporting" "Ledger-Ingest-4180"\n"migrator" "Schema-Move-2245"\n'),
    ("cfg_006", "deploy/pgbouncer/userlist.txt", False, "hash",
     '"reporting" "md5b8f3a2d61c0e7f4459a2d1bb3c7e5a90"\n'
     '"migrator" "md542f19c8b0d63ae175c2f8e9a4b16d730"\n'),
    ("cfg_007", "conf/tomcat/server.xml", True, "password",
     '<Connector port="8443" scheme="https" SSLEnabled="true"\n'
     '  keystoreFile="conf/ridgeline.jks" keystorePass="Ridgeline-Keystore-2288" />\n'),
    ("cfg_008", "conf/tomcat/server.xml", False, "default",
     '<Connector port="8443" scheme="https" SSLEnabled="true"\n'
     '  truststoreFile="conf/cacerts.jks" truststorePass="changeit" />\n'),
    ("cfg_009", "ansible/group_vars/db.yml", True, "password",
     "postgres_host: db01.larkspur.internal\npostgres_user: warehouse\n"
     "postgres_password: Beacon-Warehouse-3061\n"),
    ("cfg_010", "ansible/group_vars/db.yml", False, "reference",
     "postgres_host: db01.larkspur.internal\npostgres_user: warehouse\n"
     'postgres_password: "{{ vault_postgres_password }}"\n'),
    ("cfg_011", "etc/httpd/conf/htpasswd-source.txt", True, "password",
     "# plain source for htpasswd, run make htpasswd after editing\ndeploy:Harbor-Deploy-9954\n"
     "readonly:Harbor-Viewer-3318\n"),
    ("cfg_012", "etc/httpd/conf/.htpasswd", False, "hash",
     "deploy:$apr1$k2Vn7Hqd$Qm4pF1sT8xZbLcRwYu6dU/\n"
     "readonly:$apr1$s9Wm2Bxc$Vd7nR4gL0pKtHs3qEz1jY.\n"),
    ("cfg_013", "services/gateway/config.ini", True, "api_key",
     "[gateway]\nendpoint = https://gw.larkspur.internal\napi_key = larkspur-gateway-2f41\n"
     "timeout = 30\n"),
    ("cfg_014", "services/gateway/config.ini", False, "empty",
     "[gateway]\nendpoint = https://gw.larkspur.internal\napi_key =\napi_key_file =\n"
     "api_key_env = LARKSPUR_GATEWAY_KEY\ntimeout = 30\n"),
    ("cfg_015", "etc/rsyncd.secrets", True, "password",
     "backup:Cold-Storage-5523\nmirror:Night-Sync-8807\n"),
    ("cfg_016", "db/seeds/users.yml", False, "test_data",
     "# seeded into the local development database only, never deployed\n"
     "- email: ada@example.test\n  password: hunter2\n- email: alan@example.test\n"
     "  password: hunter2\n"),
    ("cfg_017", "docker/.env.production", True, "password",
     "REDIS_HOST=cache01.larkspur.internal\nREDIS_PASSWORD=Fenwick-Cache-6620\nREDIS_DB=2\n"),
    ("cfg_018", "docker/.env.example", False, "placeholder",
     "REDIS_HOST=cache01.example.com\nREDIS_PASSWORD=<set this in your own .env>\nREDIS_DB=2\n"),
    ("cfg_019", "etc/wpa_supplicant/wpa_supplicant.conf", True, "password",
     'network={\n  ssid="larkspur-ops"\n  psk="Rowan-Field-8834"\n  key_mgmt=WPA-PSK\n}\n'),
    ("cfg_020", "etc/openvpn/auth.txt", True, "password",
     "ops-runner\nTunnel-Access-7305\n"),
]
