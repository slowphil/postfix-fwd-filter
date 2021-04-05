#!/usr/bin/python3

# This script is an "Advanced post-queue content filter" for Postfix,
# It enables auto-forwarding e-mail through an smtp relay server

# This code is under the GNU General Public License v3.0
# Copyright Philippe Joyez 2021
# see https://github.com/slowphil/postfix-fwd-filter

## https://docs.python.org/3.7/library/smtpd.html says: 
## > smtpd should be considered deprecated.[...] The aiosmtpd package is a recommended replacement for this module.
## However, 
## 1- unlike smtpd, aiosmtpd is not included by default with python and needs to be installed (perhaps setting up a venv)
## 2- straightforward replacement requires aiosmtpd.controller.UnthreadedController in aiosmtpd v>=1.5 (not yet released as of this writing)
## For the moment we use smtpd
## If you want to use aiosmtpd instead of smtpd, delete the 2 lines below and uncomment those starting with ##
## NOTE : 3 more blocks to replace similarly below
import smtpd
import asyncore
##import asyncio
##from aiosmtpd.controller import UnthreadedController #https://aiosmtpd.readthedocs.io/en/latest/controller.html#unthreaded-controllers

import email, email.message, email.parser, email.policy, email.utils
import smtplib
import copy
import sys, time

local_domains = ["my_1stdomain.tld","my_2nddomain.tld"]
debug = False # if set to True, local recipients receive both the original message and the forwarded one
# make it False when you are confident that all mails are properly forwarded and readable upon reception.

def log(*msg):
    for i in msg: print(i,end=' ')
    print()
    sys.stdout.flush()

def unSRS(address) :
#if SRS address, decode it
    if (address[0:3] == 'SRS') and  (address[4] in ('=','+','-')) :
      sep = address[4]
      return "@".join((address.split('@')[0]).split(sep)[4:2:-1])
    else : 
      return address
      
def find_local_recipient(rcpl):
# input is a list of strings, each containing possibly several comma-separated recipients
  num = 0
  local_r = None
  for rl in rcpl:
    for r in rl.split(',') : 
      rcp= r.strip()
      chunks = email.utils.parseaddr(rcp)[1].split('@')
      if len(chunks) == 2 and chunks[1].lower() in local_domains :
          local_r = rcp
          num += 1
  return num, local_r


def resub_message(envfrom, envrcpts, msg, raise_on_fail = True) :
#smtplib.SMTPException are catched by the global catching
    smtp_client = smtplib.SMTP('127.0.0.1', 10026)
    ret = smtp_client.sendmail(envfrom, envrcpts, msg.as_bytes())
    smtp_client.quit()
    if ret == {} : 
      return "250 OK"
    else :
      refused = list(ret.keys())
      log("Server refused recipients : {} ".format(ret))
      if raise_on_fail :
        raise smtplib.SMTPException("Server refused recipients : {} ".format(refused))
      else :
        return "500 Server refused recipients : {} ".format(refused)

class myException(Exception):
    pass

## if you want to use aiosmtpd instead of smtpd, delete the 2 lines below and uncomment those starting with ##
class CustomSMTPServer(smtpd.SMTPServer):
  def process_message(self, peer, envfrom, envrcpts, data, mail_options=None, rcpt_options=None):
##class CustomHandler:
##  async def handle_DATA(self, server, session, envelope):
    '''
    PostFix doc : The simplest content filter just copies SMTP commands and data between its inputs and outputs. If it has a problem, all it has to do is to reply to an input of `.' from Postfix with `550 content rejected', and to disconnect without sending `.' on the connection that injects mail back into Postfix.
    
    Rewriting arbitrary emails is tricky. Some corner cases that would break the code may have been forgotten.
    Not delivering emails because of a bug should never go unnoticed by us: We catch ALL errors and report.
    '''
    try :
## if you want to use aiosmtpd instead of smtpd, delete the 2 lines below and uncomment those starting with ##
      msg = email.message_from_bytes(data,
            _class=email.message.EmailMessage, policy=email.policy.default)
##      envfrom = envelope.mail_from
##      envrcpts = envelope.rcpt_tos
##      msg = email.message_from_bytes(envelope.content,
##            _class=email.message.EmailMessage, policy=email.policy.default)
      canon_from = unSRS(envfrom)
      from_domain = canon_from.split('@')[1]
      if (from_domain in local_domains) :
        # send message as is, unchanged from (not de-SRSed)
        log("accept mail from {} ({}) to {}".format(envfrom, canon_from, envrcpts))
        return resub_message(envfrom, envrcpts, msg)
      else :
        fails = 0
        #separate local and remote env recipients
        local_rcpts = []
        remote_rcpts = []
        for r in envrcpts : 
          if r.split('@')[1] in local_domains :
            local_rcpts.append(r)
          else :
            remote_rcpts.append(r)
  
        # for local recipients, send as is
        # From the doc it's not clear a filter can split one message into several...
        if local_rcpts :
            log("accept mail from {} ({}) to {}".format(envfrom, canon_from, local_rcpts))
            ret_local = resub_message(envfrom, local_rcpts, msg, False)
            if ret_local[:3] != '250' :
              log("could not forward message to local recipients ({}) ".format(ret_local))
              fails += 1
        if remote_rcpts :
          # for remote recipients, the relay smtp would not transport that message
          # -> replace the sender address by a local one and format message as if it had been manually forwarded.   
          log("rewriting mail from {} ({}) to {}".format(envfrom, canon_from, remote_rcpts))
          
          msg_mod = copy.deepcopy(msg)
            
          #find an original header recipient that is in local domain, so that we can pretend they forward the message
          all_tos = (msg.get_all('To') or []) + (msg.get_all('Cc') or [])
          num_candidates, local_sender = find_local_recipient(all_tos)
          if num_candidates == 0 : 
              num_candidates, local_sender = find_local_recipient(envrcpts)
          if num_candidates != 1  : #we don't know who resends this; Fake sender to deliver anyway.
              local_sender = "courrier@"+local_domains[0] #if we have multiple local domains, pick the most likely...
          local_sender_name, local_sender_address = email.utils.parseaddr(local_sender)
   
          # change message headers. Assume everything may be missing
          subject = msg['Subject'] or ""
          if subject :
            msg_mod.replace_header('Subject', "Tr: "+subject)
          else :
            msg_mod['Subject'] = "Tr: "              
          orig_from = msg['From'] or ""
          if msg['Originally-From'] == None :
            msg_mod['Originally-From'] = orig_from
          if msg['Reply-To'] == None :
            msg_mod['Reply-To'] = orig_from
  
          name_from, address_from = email.utils.parseaddr(orig_from)
          name_from = name_from or "_at_".join(address_from.split('@'))
          if orig_from :
            msg_mod.replace_header('From', "{} via <{}>".format(name_from, local_sender_address))
          else :
            msg_mod['From'] = "{} via <{}>".format(name_from, local_sender_address)
  
          # add some body content describing the forward
          body_add = "-------- Message tranféré automatiquement par {}--------\n".format(local_sender_address)
          body_add += "Sujet: 	{}\n".format(subject)
          body_add += "Date: 	{}\n".format(msg['Date'])
          body_add += "De: 	{}\n".format(orig_from)
          body_add += "À: {}\n".format(msg['To'])
          cc = msg['Cc']
          if cc :
            body_add += "Cc: {}\n".format(cc)
          sender = msg['Sender']
          if sender :
            body_add += "Expéditeur: {}\n".format(sender)
          body_add += "-------- Message originel :--------\n"
          
          if msg['Content-Type'] == "text/plain" :
            msg_mod._payload = body_add + msg._payload
          else :
            # restructure MIME parts
            # keep all headers of msg except replace type by multipart/mixed
            # insert our added forward text
            # insert copy of original mime structure 
            # except attachements, if any, placed in top multipart/mixed
            new_part = email.message.MIMEPart(policy=email.policy.default)
            new_part.set_content(body_add)
            new_part['Content-Disposition'] = 'inline'
            msg_mod.clear_content()
            msg_mod.make_mixed()
            msg_mod.attach(new_part)
            
            # cloning the mime structure of the original msg in a temporary message
            copy_mime = email.message.MIMEPart(policy=email.policy.default)
            #preserve aspect by copying content-* headers of top mime part (drop all other headers)
            for h, v in msg._headers:
              if h.lower()[:8] == 'content-':
                copy_mime[h] = v.replace('\n',' ').replace('\r',' ')
            if msg.is_multipart() :    
              for p in msg._payload :
                if p['Content-Disposition'] != 'attachment' :
                  copy_mime.attach(p)
                else :
                  msg_mod.attach(p)
            else :
              copy_mime._payload = msg._payload
            msg_mod.attach(copy_mime)
  
          # all done, send msg
          log("forward mail from {}".format(local_sender))
          if debug :
            remote_rcpts += local_rcpts ### DEBUG period only
          ret_remote = resub_message(local_sender_address, remote_rcpts, msg_mod, False)
          if ret_remote[:3] != '250' :
            log("could not forward message to remote recipients ({}) ".format(ret_remote))
            fails += 1

        if fails == 0 :
          return '250 OK'
        else:
          raise myException("message not forwarded to some recipients")

    except Exception as e: #catch any exception 
      import traceback
      tb = traceback.format_exc()
      #some forwarding error occurred warn admin
      err_msg = "an error occured : {}".format(e)
      log(err_msg)
      log(tb)
      
      _from = "mailfilter@{}".format(local_domains[0])
      _to = "admin@{}".format(local_domains[0])
      subject = "Mail forward failed"
      message = "From: {}\n"\
      "To: {}\n"\
      "Subject: {}\n\n"\
      "when processing mail \n"\
      "from {}\n"\
      "to   {}\n"\
      "an error occured :\n"\
      "{}\n{}\n".format(_from,_to,subject,envfrom,envrcpts,err_msg,tb)
      
      try :
        s = smtplib.SMTP('127.0.0.1', 10026) # 'localhost' does not work here. We use the filter return input.
        ret = s.sendmail(_from,_to,message)       
        s.quit()
        if ret == {} : 
          log("Successfully sent email to admin")
      except smtplib.SMTPException:
        log("Unable to send email to admin")
      finally :
        return '500 Could not process your message'
    
    else :
      return '250 OK'

if __name__ == '__main__':
    log("filter starting")
## if you want to use aiosmtpd instead of smtpd, delete the 2 lines below and uncomment those starting with ##
    in_server = CustomSMTPServer(('127.0.0.1', 10025), None)
    asyncore.loop()
##    myloop = asyncio.get_event_loop()
##    handler = CustomHandler()
##    controller = UnthreadedController(handler, hostname='127.0.0.1', port=10025, loop=myloop)
##    controller.begin()
##    myloop.run_forever()
