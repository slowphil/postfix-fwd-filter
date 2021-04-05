# Forwarding filter for Postfix
A python script implementing a Postfix advanced content-filter for "auto-forwarding" through an smtp relay server.

### Issues with an email server at home :
 You run your own server at home (e.g. using [Yunohost](https://yunohost.org/#/index_en)) but your ISP blocks outbound port 25?
Then you cannot directly send your emails to whom ever you wish.
    
 One workaround is to route your traffic through a VPN. It is ideal for privacy, but it has a cost. Also, going that way, you could as well give up on self-hosting and rent a VPS… 

Another workaround is to use an **smtp relay server** that allows you to send a given number of free emails each month. However, such relay generally blocks emails that are not originating from your domain(s) in order to prevent spam and thereby preserving everyone's domains reputation. As an annoying consequence, without the present script, **your home server cannot do automatic email forwarding to outside addresses.**
 
#### Why ? 
 When your home server receives a mail and the local recipient  has defined a forward address (aka a "virtual alias" in Postfix doc) in another domain, postfix injects a new mail in the system that keeps the original `envelop From` but has a new `envelop To` not in your domain. When this message reaches the relay host, it gets blocked because its `envelop From` address is not in your domain. 
    
**Note : Privacy data handling issues with smtp relays.** An smtp relay knows whom you communicate with. For instance, Mailjet/Mailgun collects a list of all addresses you send mail to, and the list is tied to your account with them. Even if you assume they do it right, you would need to regularly cleanup this list to remain RGPD-compliant.
 
## What this script does
With this script, you may setup email forwarding following standard instructions, not bothering whether the final recipient is local or remote.

The script is a [Postfix advanced after-queue content-filter](http://www.postfix.org/FILTER_README.html#advanced_filter).  It sifts all mail in Postfix's queue, handles it as needed, and puts it back into the queue. 

For local recipients or if the mail has a local sender, we simply put back the message into the queue as is. 

For messages where both the `envelop From` and an `envelop To` are not in our domain, we do as if the original local recipient had manually forwarded the message : 

 - Replace the `envelop From` by the original local recipient (`header To` or `envelop To`) (so that the relay host is happy)
 - replace `header From` so that spam checkers are happy too
 - add `Reply-to` header, to make it easy to reply to the original sender
 - add "Fw:" in front of subject
 - add some text to the body, as if the mail had been manually forwarded:
    -------- Forwarded Message --------
Subject:        header subject
Date:           env date
From:           header from
To:                     env rcpt
    ----------------------------------

## Setting up

Copy the script to your server. Edit the script line 27 and change the local domain(s) handled by your server :

```
local_domains = ["my1stdomain.tld","my2nddomain.tld"]
```

#### Autostart with systemd

1. Edit the content of `fwd_filter.service` to point where you installed the script and copy (or link) the edited `fwd_filter.service` file in `/etc/systemd/system`. 
2. Then define an unprivileged user that will run the filter daemon
```
sudo adduser --system --no-create-home --group mailfilter
```
3.  and instruct systemd to activate the service
```
sudo systemctl enable fwd_filter.service
sudo systemctl start fwd_filter.service
```

#### Make changes in Postfix conf files :
in `/etc/postfix/main.cf` add: 
```
content_filter = fwd_filter:localhost:10025
#receive_override_options =       # no override, we need all mappings done
```
in `/etc/postfix/master.cf` add: 
```
fwd_filter      unix  -       -       n       -       1      smtp
  -o smtp_send_xforward_command=yes
  -o disable_mime_output_conversion=yes
  -o smtp_generic_maps=
localhost:10026 inet  n       -       n       -       1      smtpd
        -o content_filter= 
        -o receive_override_options=no_unknown_recipient_checks,no_header_body_checks,no_milters,no_address_mappings
        -o smtpd_helo_restrictions=
        -o smtpd_client_restrictions=
        -o smtpd_sender_restrictions=
        # Postfix 2.10 and later: specify empty smtpd_relay_restrictions.
        -o smtpd_relay_restrictions=
        -o smtpd_recipient_restrictions=permit_mynetworks,reject
        -o mynetworks=127.0.0.0/8
        -o smtpd_authorized_xforward_hosts=127.0.0.0/8
```

Finally, make your changes active :
```
sudo postfix reload
```