# 🔐 Lab LDAP sur Ubuntu – mirecloud.com

Ce dépôt documente l’installation et la configuration d’un serveur **LDAP (OpenLDAP)** pour le domaine **mirecloud.com**.

Objectif : implémenter un annuaire prêt pour l’intégration avec Keycloak, Linux (SSSD) et Kubernetes.

---

## 📌 Informations de base

| Élément | Valeur |
|--------|--------|
| Domaine LDAP | mirecloud.com |
| Base DN | dc=mirecloud,dc=com |
| Admin DN | cn=admin,dc=mirecloud,dc=com |
| Organisation | MIRECLOUD |
| OU utilisateurs | ou=users,dc=mirecloud,dc=com |
| OU groupes | ou=groups,dc=mirecloud,dc=com |

---

## 🚀 Installation OpenLDAP

### Mise à jour
```bash
sudo apt update && sudo apt upgrade -y
sudo reboot
```

### Installation de OpenLDAP
```bash
sudo apt install slapd ldap-utils -y
```

### Reconfiguration propre
```bash
sudo dpkg-reconfigure slapd
```

Valeurs à entrer :

| Question | Réponse |
|--------|---------|
| Omit OpenLDAP configuration? | No |
| DNS domain name | mirecloud.com |
| Organization | MIRECLOUD |
| Admin password | Mot de passe fort |
| Backend | MDB |
| Remove db on purge | No |
| Move old database | Yes |
| Allow LDAPv2 | No |

---

## ✅ Vérification

```bash
ldapwhoami -x
```

```bash
ldapwhoami -x -D cn=admin,dc=mirecloud,dc=com -W
```

---

## 📁 Création de la structure LDAP

Créer `base.ldif` :

```ldif
dn: ou=users,dc=mirecloud,dc=com
objectClass: organizationalUnit
ou: users

dn: ou=groups,dc=mirecloud,dc=com
objectClass: organizationalUnit
ou: groups
```

Appliquer :

```bash
ldapadd -x -D cn=admin,dc=mirecloud,dc=com -W -f base.ldif
```

---

## 👤 Ajout d’un utilisateur

Créer `user.ldif` :

```ldif
dn: uid=emmanuel,ou=users,dc=mirecloud,dc=com
objectClass: inetOrgPerson
objectClass: posixAccount
objectClass: shadowAccount
cn: Emmanuel
sn: Ledoux
uid: emmanuel
uidNumber: 10000
gidNumber: 10000
homeDirectory: /home/emmanuel
loginShell: /bin/bash
```

Ajouter :

```bash
ldapadd -x -D cn=admin,dc=mirecloud,dc=com -W -f user.ldif
```

---

## 🔑 Attribuer un mot de passe

```bash
ldappasswd -x -D cn=admin,dc=mirecloud,dc=com -W uid=emmanuel,ou=users,dc=mirecloud,dc=com
```

---

## 🔎 Vérification LDAP

```bash
ldapsearch -x -b dc=mirecloud,dc=com
```

---

## 🌐 Interface Web (optionnelle)

```bash
sudo apt install phpldapadmin -y
```

Accès navigateur :

```
http://IP_DU_SERVEUR/phpldapadmin
```

Login :
- DN : cn=admin,dc=mirecloud,dc=com
- Mot de passe : ton mot de passe LDAP

---

## ⚙️ Prochaines étapes

Après ce lab, tu peux enchaîner :

- Intégration avec Keycloak
- Auth Linux via SSSD
- Intégration Kubernetes avec OIDC
- Sécurisation TLS de LDAP

---

## 👔 Usage CV

> Déploiement d’un annuaire OpenLDAP pour mirecloud.com, structuration utilisateurs & groupes, préparation IAM et SSO.

---

✅ Statut : fonctionnel & prêt pour extension IAM
