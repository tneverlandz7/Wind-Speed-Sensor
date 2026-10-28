#pragma once
#include <cstdint>
#include <string>
#include <cstdlib>
#include <cmath>
#include <cstring>
#include <cctype>
using std::isfinite;
class String {
 std::string str;
 public:
 String()=default; String(const char *s):str(s?s:""){} String(std::string s):str(s){}
 void trim(){auto l=str.find_first_not_of(" \r\n\t"); if(l==std::string::npos){str.clear();return;} auto r=str.find_last_not_of(" \r\n\t");str=str.substr(l,r-l+1);}
 bool startsWith(const char *s)const{return str.rfind(s,0)==0;}
 int length()const{return (int)str.size();}
 void toCharArray(char *a,unsigned long n)const{ if(n){strncpy(a,str.c_str(),n-1);a[n-1]='\0';}}
 char charAt(int i)const{return str.at(i);}
 String substring(int i)const{return str.substr(i);}
 float toFloat()const{return strtof(str.c_str(),nullptr);}
};
struct FakeSerial {
 void begin(int){} void setTimeout(int){} bool available(){return false;} int read(){return 0;}
 String readStringUntil(char){return String();}
 template<typename T>void print(T){} template<typename T>void print(T,int){}
 template<typename T>void println(T){} template<typename T>void println(T,int){}
 void println(){}
};
extern FakeSerial Serial;
inline void delay(unsigned long){}
extern unsigned long fakeUs;
inline unsigned long millis(){return fakeUs/1000;}
inline unsigned long micros(){return fakeUs;}
#define PB9 9
#define PB8 8
#define HEX 16
